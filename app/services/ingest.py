import json
import logging
from typing import Any

from app.models.domain import NormalizedMessage
from app.sheets.client import GoogleSheetsClient
from app.sheets.rows import build_messages_row
from app.storage.sqlite import DuplicateEventError, IngestEventRepository
from app.telegram.parser import TelegramUpdateParser

logger = logging.getLogger(__name__)


class IngestService:
    def __init__(
        self,
        parser: TelegramUpdateParser,
        events: IngestEventRepository,
        sheets: GoogleSheetsClient,
        sync_batch_size: int,
    ) -> None:
        self.parser = parser
        self.events = events
        self.sheets = sheets
        self.sync_batch_size = sync_batch_size

    def ingest_update(self, update: dict[str, Any]) -> dict[str, Any]:
        update_id = update.get("update_id")
        logger.info("update received", extra={"_update_id": update_id})

        result = self.parser.parse(update)
        if result.is_ignored:
            logger.info(
                "update ignored",
                extra={"_update_id": update_id, "_reason": result.ignore_reason},
            )
            return {"status": "ignored", "reason": result.ignore_reason}

        message = self._require_message(result.message)
        row = build_messages_row(message)
        try:
            event_id = self.events.create_pending(message, row)
        except DuplicateEventError:
            logger.info(
                "duplicate skipped",
                extra={
                    "_update_id": message.telegram_update_id,
                    "_chat_id": message.telegram_chat_id,
                    "_message_id": message.telegram_message_id,
                },
            )
            return {"status": "duplicate"}

        logger.info(
            "normalized message created",
            extra={
                "_event_id": event_id,
                "_update_id": message.telegram_update_id,
                "_source_type": message.source_type.value,
                "_chat_id": message.telegram_chat_id,
                "_message_id": message.telegram_message_id,
            },
        )
        return {"status": "accepted", "event_id": event_id}

    def sync_pending_once(self) -> int:
        synced = 0
        for event in self.events.get_pending(self.sync_batch_size):
            event_id = int(event["id"])
            try:
                row = json.loads(event["sheets_row_json"])
                self.sheets.append_row(row)
                self.events.mark_synced(event_id)
                synced += 1
                logger.info(
                    "appended to sheets",
                    extra={
                        "_event_id": event_id,
                        "_update_id": event["update_id"],
                        "_chat_id": event["chat_id"],
                        "_message_id": event["message_id"],
                    },
                )
            except Exception as exc:
                self.events.mark_failed(event_id, str(exc))
                logger.error(
                    "error on sheets write",
                    extra={"_event_id": event_id, "_error": str(exc)},
                    exc_info=True,
                )
        return synced

    def ensure_sheets_ready(self) -> None:
        self.sheets.ensure_messages_header()

    def _require_message(self, message: NormalizedMessage | None) -> NormalizedMessage:
        if message is None:
            raise RuntimeError("parser returned empty non-ignored result")
        return message
