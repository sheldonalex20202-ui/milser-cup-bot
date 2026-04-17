from functools import lru_cache

from app.core.config import Settings, get_settings
from app.services.ingest import IngestService
from app.sheets.client import GoogleSheetsClient
from app.storage.sqlite import IngestEventRepository, SQLiteDatabase, ThreadMappingRepository
from app.telegram.parser import TelegramUpdateParser


@lru_cache
def get_database() -> SQLiteDatabase:
    return SQLiteDatabase(get_settings().sqlite_path)


@lru_cache
def get_ingest_service() -> IngestService:
    settings: Settings = get_settings()
    db = get_database()
    thread_mappings = ThreadMappingRepository(db)
    parser = TelegramUpdateParser(settings, thread_mappings)
    sheets = GoogleSheetsClient(
        credentials_path=settings.google_credentials_path,
        credentials_json=settings.google_credentials_json,
        spreadsheet_id=settings.google_spreadsheet_id,
        append_range=settings.google_append_range,
        sheet_name=settings.google_messages_sheet_name,
    )
    return IngestService(
        parser=parser,
        events=IngestEventRepository(db),
        sheets=sheets,
        sync_batch_size=settings.sync_batch_size,
    )
