import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status

from app.core.config import Settings, get_settings
from app.services.ingest import IngestService
from app.services.ticket import TicketService
from app.api.dependencies import get_ingest_service, get_ticket_service
from app.models.domain import NormalizedMessage

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/health")
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
        background_tasks.add_task(ticket_svc.handle_callback, update["callback_query"])
        return {"ok": True, "status": "callback_queued"}

    # --- Admin reply in community DM topic (on behalf of community) ---
    if ticket_svc.is_community_dm_reply(update):
        background_tasks.add_task(ticket_svc.handle_community_dm_reply, update.get("message", {}))
        return {"ok": True, "status": "community_dm_reply_queued"}

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
    return {"ok": True, "messages_synced": messages_synced, "tickets_synced": tickets_synced}


def _create_ticket_safe(ticket_svc: TicketService, message: NormalizedMessage) -> None:
    try:
        ticket_svc.create_ticket(message)
    except Exception as exc:
        logger.error("ticket creation failed", extra={"_error": str(exc)}, exc_info=True)
