from datetime import datetime, timezone
from typing import Any

from app.models.ticket import Ticket
from app.storage.sqlite import SQLiteDatabase


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TicketRepository:
    def __init__(self, db: SQLiteDatabase) -> None:
        self.db = db

    def create(
        self,
        source_type: str,
        user_id: int,
        username: str | None,
        first_name: str | None,
        user_chat_id: int,
        user_message_id: int,
        user_message_thread_id: int | None,
        user_message_text: str | None,
    ) -> "Ticket":
        now = _utc_now()
        with self.db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO tickets (
                    source_type, user_id, username, first_name,
                    user_chat_id, user_message_id, user_message_thread_id,
                    user_message_text, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_type, user_id, username, first_name,
                    user_chat_id, user_message_id, user_message_thread_id,
                    user_message_text, now,
                ),
            )
            ticket_id = int(cursor.lastrowid)
            code = f"TKT-{ticket_id:05d}"
            conn.execute("UPDATE tickets SET ticket_code = ? WHERE id = ?", (code, ticket_id))
        return self.get_by_id(ticket_id)  # type: ignore[return-value]

    def set_support_message(self, ticket_id: int, support_group_message_id: int) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE tickets SET support_group_message_id = ? WHERE id = ?",
                (support_group_message_id, ticket_id),
            )

    def mark_reacted(self, ticket_id: int, reacted_by: int) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE tickets
                SET status = 'reacted', reacted_at_utc = ?, reacted_by_user_id = ?
                WHERE id = ? AND status = 'new'
                """,
                (_utc_now(), reacted_by, ticket_id),
            )

    def mark_answered(self, ticket_id: int, answer_message_id: int) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE tickets
                SET status = 'answered', answered_at_utc = ?, answer_message_id = ?
                WHERE id = ? AND status IN ('new', 'reacted')
                """,
                (_utc_now(), answer_message_id, ticket_id),
            )

    def mark_closed(self, ticket_id: int, closed_by: int) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE tickets
                SET status = 'closed', closed_at_utc = ?, closed_by_user_id = ?
                WHERE id = ? AND status IN ('new', 'reacted', 'answered')
                """,
                (_utc_now(), closed_by, ticket_id),
            )

    def mark_sheets_synced(self, ticket_id: int) -> None:
        with self.db.connect() as conn:
            conn.execute("UPDATE tickets SET sheets_synced = 1 WHERE id = ?", (ticket_id,))

    def get_by_id(self, ticket_id: int) -> Ticket | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
            return Ticket(dict(row)) if row else None

    def get_by_support_message(self, support_group_message_id: int) -> Ticket | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM tickets WHERE support_group_message_id = ?",
                (support_group_message_id,),
            ).fetchone()
            return Ticket(dict(row)) if row else None

    def get_unsync_closed(self, limit: int = 50) -> list[Ticket]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tickets WHERE status = 'closed' AND sheets_synced = 0 ORDER BY id LIMIT ?",
                (limit,),
            ).fetchall()
            return [Ticket(dict(r)) for r in rows]
