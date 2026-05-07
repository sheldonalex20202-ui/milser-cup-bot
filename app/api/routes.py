import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.services.ingest import IngestService
from app.services.ticket import TicketService
from app.api.dependencies import get_ingest_service, get_ticket_service
from app.api.broadcast_ui import render_direct_broadcast_ui
from app.models.domain import NormalizedMessage
from app.services.broadcast import DirectBroadcastRecipient, DirectBroadcastService
from app.services.broadcast_lookup import GoogleSheetsDirectRecipientLookup, recipients_from_found
from app.telegram.sender import TelegramSender

router = APIRouter()
logger = logging.getLogger(__name__)


class DirectBroadcastRecipientPayload(BaseModel):
    chat_id: int
    direct_messages_topic_id: int
    user_id: int | None = None
    username: str | None = None


class DirectBroadcastPayload(BaseModel):
    text: str = Field(..., min_length=1, max_length=4096)
    recipients: list[DirectBroadcastRecipientPayload] = Field(..., min_length=1, max_length=1000)
    dry_run: bool = True
    delay_seconds: float = Field(default=1.0, ge=0.0, le=60.0)


class DirectBroadcastByUsernamesPayload(BaseModel):
    text: str = Field(..., min_length=1, max_length=4096)
    usernames: list[str] = Field(..., min_length=1, max_length=5000)
    direct_chat_id: int | None = None
    dry_run: bool = True
    delay_seconds: float = Field(default=1.0, ge=0.0, le=60.0)


@router.api_route("/", methods=["GET", "HEAD"])
def root() -> dict[str, str]:
    return {"status": "ok"}


@router.api_route("/health", methods=["GET", "HEAD"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    ingest: IngestService = Depends(get_ingest_service),
    ticket_svc: TicketService = Depends(get_ticket_service),
) -> dict[str, Any]:
    if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid webhook secret")

    update = await request.json()

    # --- Callback query (button click) ---
    if "callback_query" in update:
        callback_query = update["callback_query"]
        background_tasks.add_task(ticket_svc.handle_callback, callback_query, False)
        return ticket_svc.build_callback_ack(callback_query)

    # --- Admin reply in community DM topic (on behalf of community) ---
    if ticket_svc.is_community_dm_reply(update):
        background_tasks.add_task(ticket_svc.handle_community_dm_reply, update.get("message", {}))
        return {"ok": True, "status": "community_dm_reply_queued"}

    # --- Support command: list active tickets ---
    if ticket_svc.is_ticket_list_command(update):
        message = update.get("message", {})
        logger.info(
            "support ticket list command received",
            extra={
                "_chat_id": (message.get("chat") or {}).get("id"),
                "_message_thread_id": message.get("message_thread_id"),
                "_message_id": message.get("message_id"),
                "_text": message.get("text"),
            },
        )
        ticket_svc.handle_ticket_list_command(message)
        return {"ok": True, "status": "ticket_list_sent"}

    # --- Admin reply to a ticket message in support group ---
    if ticket_svc.is_admin_reply(update):
        message = update.get("message", {})
        background_tasks.add_task(ticket_svc.handle_admin_reply, message)
        return {"ok": True, "status": "admin_reply_queued"}

    # --- Community message: ingest + create ticket ---
    result = ingest.ingest_update(update)

    if result.get("status") == "accepted":
        normalized: NormalizedMessage | None = result.get("normalized_message")
        if normalized is not None:
            background_tasks.add_task(_create_ticket_safe, ticket_svc, normalized)
        if settings.sync_on_ingest:
            background_tasks.add_task(ingest.sync_pending_once)

    result_response = {k: v for k, v in result.items() if k != "normalized_message"}
    return {"ok": True, **result_response}


@router.post("/internal/sync-pending")
def sync_pending(
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    ingest: IngestService = Depends(get_ingest_service),
    ticket_svc: TicketService = Depends(get_ticket_service),
) -> dict[str, Any]:
    if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid secret")
    messages_synced = ingest.sync_pending_once()
    tickets_synced = ticket_svc.sync_closed_tickets()
    alerts_sent = ticket_svc.check_stale_tickets()
    return {"ok": True, "messages_synced": messages_synced, "tickets_synced": tickets_synced, "alerts_sent": alerts_sent}


@router.get("/internal/broadcast/direct/ui", response_class=HTMLResponse)
def direct_broadcast_ui(settings: Settings = Depends(get_settings)) -> str:
    # Do not expose the production webhook secret in HTML. Test contour can inject it separately.
    webhook_secret = settings.telegram_webhook_secret_token if settings.environment == "test" else ""
    return render_direct_broadcast_ui(webhook_secret)


@router.post("/internal/broadcast/direct")
def direct_broadcast(
    payload: DirectBroadcastPayload,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid secret")

    recipients = [
        DirectBroadcastRecipient(
            chat_id=item.chat_id,
            direct_messages_topic_id=item.direct_messages_topic_id,
            user_id=item.user_id,
            username=item.username,
        )
        for item in payload.recipients
    ]
    result = DirectBroadcastService(TelegramSender(settings.telegram_bot_token)).send(
        payload.text,
        recipients,
        dry_run=payload.dry_run,
        delay_seconds=payload.delay_seconds,
    )
    return {"ok": True, **result}


@router.post("/internal/broadcast/direct/by-usernames")
def direct_broadcast_by_usernames(
    payload: DirectBroadcastByUsernamesPayload,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid secret")

    lookup = GoogleSheetsDirectRecipientLookup(settings).lookup(
        payload.usernames,
        direct_chat_id=payload.direct_chat_id,
    )
    recipients = recipients_from_found(lookup["found"])
    result = DirectBroadcastService(TelegramSender(settings.telegram_bot_token)).send(
        payload.text,
        recipients,
        dry_run=payload.dry_run,
        delay_seconds=payload.delay_seconds,
    )
    return {"ok": True, "lookup": lookup, **result}


def _create_ticket_safe(ticket_svc: TicketService, message: NormalizedMessage) -> None:
    try:
        ticket_svc.create_ticket(message)
    except Exception as exc:
        logger.error("ticket creation failed", extra={"_error": str(exc)}, exc_info=True)
