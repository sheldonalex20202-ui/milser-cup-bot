import json
import re
from contextlib import contextmanager
from queue import Empty, LifoQueue
from threading import Lock
from typing import Any, Iterator

from app.models.domain import NormalizedMessage
from app.storage.sqlite import DuplicateEventError


class PostgresDatabase:
    def __init__(self, database_url: str, schema: str = "bot_test", pool_size: int = 5) -> None:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
            raise ValueError("Postgres schema name must be a simple identifier")
        self.database_url = database_url
        self.schema = schema
        self.pool_size = pool_size
        self._pool: LifoQueue[Any] = LifoQueue(maxsize=pool_size)
        self._created = 0
        self._lock = Lock()

    def initialize(self) -> None:
        # Supabase schema is managed by test/supabase/migrations.
        return None

    @contextmanager
    def connect(self) -> Iterator[Any]:
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._release_connection(conn)

    def close(self) -> None:
        while True:
            try:
                conn = self._pool.get_nowait()
            except Empty:
                return
            try:
                conn.close()
            except Exception:
                pass

    def _get_connection(self) -> Any:
        try:
            conn = self._pool.get_nowait()
            if not conn.closed:
                return conn
        except Empty:
            pass

        with self._lock:
            self._created += 1

        import psycopg
        from psycopg.rows import dict_row

        conn = psycopg.connect(self.database_url, row_factory=dict_row)
        conn.execute(f"set search_path to {self.schema}, public")
        conn.commit()
        return conn

    def _release_connection(self, conn: Any) -> None:
        if conn.closed:
            return
        try:
            self._pool.put_nowait(conn)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass


class PostgresThreadMappingRepository:
    def __init__(self, db: PostgresDatabase) -> None:
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
                insert into discussion_thread_mappings (
                    discussion_chat_id, message_thread_id, channel_chat_id,
                    channel_post_id, root_message_id, updated_at_utc
                )
                values (%s, %s, %s, %s, %s, now())
                on conflict (discussion_chat_id, message_thread_id) do update set
                    channel_chat_id = excluded.channel_chat_id,
                    channel_post_id = excluded.channel_post_id,
                    root_message_id = excluded.root_message_id,
                    updated_at_utc = excluded.updated_at_utc
                """,
                (discussion_chat_id, message_thread_id, channel_chat_id, channel_post_id, root_message_id),
            )

    def get(self, discussion_chat_id: int, message_thread_id: int) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                select channel_chat_id, channel_post_id, root_message_id
                from discussion_thread_mappings
                where discussion_chat_id = %s and message_thread_id = %s
                """,
                (discussion_chat_id, message_thread_id),
            ).fetchone()
            return dict(row) if row else None


class PostgresIngestEventRepository:
    def __init__(self, db: PostgresDatabase) -> None:
        self.db = db

    def create_pending(self, message: NormalizedMessage, row: list[Any]) -> int:
        import psycopg

        try:
            with self.db.connect() as conn:
                result = conn.execute(
                    """
                    insert into ingest_events (
                        update_id, chat_id, message_id, source_type, status,
                        normalized_json, sheets_row_json, created_at_utc
                    )
                    values (%s, %s, %s, %s, 'pending', %s::jsonb, %s::jsonb, now())
                    returning id
                    """,
                    (
                        message.telegram_update_id,
                        message.telegram_chat_id,
                        message.telegram_message_id,
                        message.source_type.value,
                        message.model_dump_json(),
                        json.dumps(row, ensure_ascii=False, default=str),
                    ),
                ).fetchone()
                return int(result["id"])
        except psycopg.errors.UniqueViolation as exc:
            raise DuplicateEventError(str(exc)) from exc

    def get_pending(self, limit: int) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                select id, update_id, chat_id, message_id, attempts, sheets_row_json
                from ingest_events
                where status in ('pending', 'failed')
                order by id
                limit %s
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def mark_synced(self, event_id: int) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                update ingest_events
                set status = 'synced', synced_at_utc = now(), last_error = null
                where id = %s
                """,
                (event_id,),
            )

    def mark_failed(self, event_id: int, error: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                update ingest_events
                set status = 'failed', attempts = attempts + 1, last_error = %s
                where id = %s
                """,
                (error[:2000], event_id),
            )
