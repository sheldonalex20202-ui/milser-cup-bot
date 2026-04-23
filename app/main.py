from contextlib import asynccontextmanager
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
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Telegram Community Logger", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()
