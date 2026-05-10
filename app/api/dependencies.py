from functools import lru_cache

from app.core.config import Settings, get_settings
from app.services.ingest import IngestService
from app.services.ticket import TicketService
from app.sheets.client import GoogleSheetsClient
from app.sheets.fake import FakeGoogleSheetsClient
from app.storage.postgres import PostgresDatabase, PostgresIngestEventRepository, PostgresThreadMappingRepository
from app.storage.postgres_tickets import PostgresTicketRepository
from app.storage.sqlite import IngestEventRepository, SQLiteDatabase, ThreadMappingRepository
from app.storage.tickets import TicketRepository
from app.telegram.parser import TelegramUpdateParser
from app.telegram.sender import TelegramSender


@lru_cache
def get_database() -> SQLiteDatabase | PostgresDatabase:
    settings = get_settings()
    if settings.storage_backend == "supabase":
        if not settings.supabase_database_url:
            raise RuntimeError("SUPABASE_DATABASE_URL is required when STORAGE_BACKEND=supabase")
        return PostgresDatabase(settings.supabase_database_url, schema=settings.supabase_schema)
    return SQLiteDatabase(settings.sqlite_path)


@lru_cache
def get_sheets_client() -> GoogleSheetsClient:
    settings: Settings = get_settings()
    if settings.environment == "test" and not settings.google_credentials_json:
        credentials_path = settings.google_credentials_path
        if credentials_path is None or not credentials_path.exists():
            return FakeGoogleSheetsClient(settings.sqlite_path.parent)  # type: ignore[return-value]
    return GoogleSheetsClient(
        credentials_path=settings.google_credentials_path,
        credentials_json=settings.google_credentials_json,
        spreadsheet_id=settings.google_spreadsheet_id,
        append_range=settings.google_append_range,
        sheet_name=settings.google_messages_sheet_name,
        tickets_sheet_name=settings.google_tickets_sheet_name,
    )


@lru_cache
def get_ingest_service() -> IngestService:
    settings: Settings = get_settings()
    db = get_database()
    if settings.storage_backend == "supabase":
        thread_mappings = PostgresThreadMappingRepository(db)  # type: ignore[arg-type]
        events = PostgresIngestEventRepository(db)  # type: ignore[arg-type]
    else:
        thread_mappings = ThreadMappingRepository(db)  # type: ignore[arg-type]
        events = IngestEventRepository(db)  # type: ignore[arg-type]
    parser = TelegramUpdateParser(settings, thread_mappings)
    return IngestService(
        parser=parser,
        events=events,
        sheets=get_sheets_client(),
        sync_batch_size=settings.sync_batch_size,
    )


@lru_cache
def get_ticket_repository() -> TicketRepository | PostgresTicketRepository:
    settings: Settings = get_settings()
    db = get_database()
    if settings.storage_backend == "supabase":
        return PostgresTicketRepository(db)  # type: ignore[arg-type]
    return TicketRepository(db)  # type: ignore[arg-type]


@lru_cache
def get_ticket_service() -> TicketService:
    settings: Settings = get_settings()
    if not settings.telegram_support_group_chat_id:
        raise RuntimeError("TELEGRAM_SUPPORT_GROUP_CHAT_ID is not configured")
    sender = TelegramSender(settings.telegram_bot_token)
    tickets = get_ticket_repository()
    return TicketService(
        tickets=tickets,
        sender=sender,
        sheets=get_sheets_client(),
        support_group_chat_id=settings.telegram_support_group_chat_id,
        bot_user_id=settings.telegram_bot_user_id,
        tz_offset=settings.ticket_timezone_offset_hours,
        day_start_hour=settings.ticket_day_start_hour,
        night_start_hour=settings.ticket_night_start_hour,
        community_username=settings.telegram_community_username,
        support_topic_comments=settings.telegram_support_topic_comments,
        support_topic_direct=settings.telegram_support_topic_direct,
        support_topic_warnings=settings.telegram_support_topic_warnings,
        support_admin_user_ids=settings.telegram_support_admin_user_ids,
        alert_threshold_seconds=settings.ticket_alert_threshold_seconds,
        alert_repeat_seconds=settings.ticket_alert_repeat_seconds,
    )
