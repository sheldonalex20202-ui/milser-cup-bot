from functools import lru_cache

from app.core.config import Settings, get_settings
from app.services.ingest import IngestService
from app.services.ticket import TicketService
from app.sheets.client import GoogleSheetsClient
from app.storage.sqlite import IngestEventRepository, SQLiteDatabase, ThreadMappingRepository
from app.storage.tickets import TicketRepository
from app.telegram.parser import TelegramUpdateParser
from app.telegram.sender import TelegramSender


@lru_cache
def get_database() -> SQLiteDatabase:
    return SQLiteDatabase(get_settings().sqlite_path)


@lru_cache
def get_sheets_client() -> GoogleSheetsClient:
    settings: Settings = get_settings()
    return GoogleSheetsClient(
        credentials_path=settings.google_credentials_path,
        credentials_json=settings.google_credentials_json,
        spreadsheet_id=settings.google_spreadsheet_id,
        append_range=settings.google_append_range,
        sheet_name=settings.google_messages_sheet_name,
    )


@lru_cache
def get_ingest_service() -> IngestService:
    settings: Settings = get_settings()
    db = get_database()
    thread_mappings = ThreadMappingRepository(db)
    parser = TelegramUpdateParser(settings, thread_mappings)
    return IngestService(
        parser=parser,
        events=IngestEventRepository(db),
        sheets=get_sheets_client(),
        sync_batch_size=settings.sync_batch_size,
    )


@lru_cache
def get_ticket_service() -> TicketService:
    settings: Settings = get_settings()
    if not settings.telegram_support_group_chat_id:
        raise RuntimeError("TELEGRAM_SUPPORT_GROUP_CHAT_ID is not configured")
    sender = TelegramSender(settings.telegram_bot_token)
    tickets = TicketRepository(get_database())
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
    )
