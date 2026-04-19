from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.dependencies import get_database, get_ingest_service, get_ticket_service
from app.api.routes import router
from app.core.config import get_settings
from app.core.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    get_database().initialize()
    ingest = get_ingest_service()
    ingest.ensure_sheets_ready()
    ingest.sync_pending_once()
    if settings.telegram_support_group_chat_id:
        ticket_svc = get_ticket_service()
        ticket_svc.ensure_sheets_ready()
        ticket_svc.sync_closed_tickets()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Telegram Community Logger", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()
