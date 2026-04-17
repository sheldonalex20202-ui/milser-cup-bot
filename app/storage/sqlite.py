import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.models.domain import NormalizedMessage


class DuplicateEventError(Exception):
    pass


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self, migration_path: Path = Path("migrations/001_init.sql")) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(migration_path.read_text(encoding="utf-8"))

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


class ThreadMappingRepository:
    def __init__(self, db: SQLiteDatabase) -> None:
        self.db = db

    def upsert(
        self,
        discussion_chat_id: int,
        message_thread_id: int,
        channel_chat_id: int | None,
        channel_post_id: int | None,
        root_message_id: int | None,
    ) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO discussion_thread_mappings (
                    discussion_chat_id,
                    message_thread_id,
                    channel_chat_id,
                    channel_post_id,
                    root_message_id,
                    updated_at_utc
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(discussion_chat_id, message_thread_id) DO UPDATE SET
                    channel_chat_id = excluded.channel_chat_id,
                    channel_post_id = excluded.channel_post_id,
                    root_message_id = excluded.root_message_id,
                    updated_at_utc = excluded.updated_at_utc
                """,
                (
                    discussion_chat_id,
                    message_thread_id,
                    channel_chat_id,
                    channel_post_id,
                    root_message_id,
                    utc_now_iso(),
                ),
            )

    def get(self, discussion_chat_id: int, message_thread_id: int) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT channel_chat_id, channel_post_id, root_message_id
                FROM discussion_thread_mappings
                WHERE discussion_chat_id = ? AND message_thread_id = ?
                """,
                (discussion_chat_id, message_thread_id),
            ).fetchone()
            return dict(row) if row else None


class IngestEventRepository:
    def __init__(self, db: SQLiteDatabase) -> None:
        self.db = db

    def create_pending(self, message: NormalizedMessage, row: list[Any]) -> int:
        try:
            with self.db.connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO ingest_events (
                        update_id,
                        chat_id,
                        message_id,
                        source_type,
                        status,
                        normalized_json,
                        sheets_row_json,
                        created_at_utc
                    )
                    VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)
                    """,
                    (
                        message.telegram_update_id,
                        message.telegram_chat_id,
                        message.telegram_message_id,
                        message.source_type.value,
                        message.model_dump_json(),
                        json.dumps(row, ensure_ascii=False, default=str),
                        utc_now_iso(),
                    ),
                )
                return int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise DuplicateEventError(str(exc)) from exc

    def get_pending(self, limit: int) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, update_id, chat_id, message_id, attempts, sheets_row_json
                FROM ingest_events
                WHERE status IN ('pending', 'failed')
                ORDER BY id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def mark_synced(self, event_id: int) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE ingest_events
                SET status = 'synced', synced_at_utc = ?, last_error = NULL
                WHERE id = ?
                """,
                (utc_now_iso(), event_id),
            )

    def mark_failed(self, event_id: int, error: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE ingest_events
                SET status = 'failed',
                    attempts = attempts + 1,
                    last_error = ?
                WHERE id = ?
                """,
                (error[:2000], event_id),
            )
