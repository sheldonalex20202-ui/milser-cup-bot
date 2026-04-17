from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status

from app.core.config import Settings, get_settings
from app.services.ingest import IngestService
from app.api.dependencies import get_ingest_service

router = APIRouter()


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
) -> dict[str, Any]:
    if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid webhook secret")

    update = await request.json()
    result = ingest.ingest_update(update)
    if settings.sync_on_ingest and result.get("status") == "accepted":
        background_tasks.add_task(ingest.sync_pending_once)
    return {"ok": True, **result}


@router.post("/internal/sync-pending")
def sync_pending(
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    ingest: IngestService = Depends(get_ingest_service),
) -> dict[str, Any]:
    if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid secret")
    return {"ok": True, "synced": ingest.sync_pending_once()}
