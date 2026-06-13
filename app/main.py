from contextlib import asynccontextmanager
import asyncio
import logging

from fastapi import FastAPI

from app.api.dependencies import get_database, get_ingest_service, get_ticket_service
from app.api.routes import router
from app.core.config import get_settings
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    get_database().initialize()
    if settings.startup_sync_enabled:
        try:
            ingest = get_ingest_service()
            ingest.ensure_sheets_ready()
            ingest.sync_pending_once()
        except Exception as exc:
            logger.warning(
                "startup messages sheets sync failed, will retry later",
                extra={"_error": str(exc)},
                exc_info=True,
            )
        if settings.telegram_support_group_chat_id:
            try:
                ticket_svc = get_ticket_service()
                ticket_svc.ensure_sheets_ready()
                ticket_svc.sync_closed_tickets()
            except Exception as exc:
                logger.warning(
                    "startup tickets sheets sync failed, will retry later",
                    extra={"_error": str(exc)},
                    exc_info=True,
                )
    else:
        logger.info("startup sheets sync disabled")
    alert_task: asyncio.Task | None = None
    warnings_topic = getattr(settings, "telegram_support_topic_warnings", None)
    alert_interval = getattr(settings, "ticket_alert_check_interval_seconds", 30)
    alerts_enabled = getattr(settings, "ticket_alerts_enabled", False)
    if settings.telegram_support_group_chat_id and warnings_topic and alerts_enabled:
        alert_task = asyncio.create_task(_ticket_alert_loop(alert_interval))
    try:
        yield
    finally:
        if alert_task:
            alert_task.cancel()
            try:
                await alert_task
            except asyncio.CancelledError:
                pass
        db = get_database()
        close = getattr(db, "close", None)
        if close:
            close()


def create_app() -> FastAPI:
    app = FastAPI(title="Telegram Community Logger", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()


async def _ticket_alert_loop(interval_seconds: int) -> None:
    while True:
        await asyncio.sleep(max(interval_seconds, 5))
        try:
            ticket_svc = get_ticket_service()
            sent = await asyncio.to_thread(ticket_svc.check_stale_tickets)
            if sent:
                logger.info("ticket alerts sent", extra={"_count": sent})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("ticket alert loop failed", extra={"_error": str(exc)}, exc_info=True)
