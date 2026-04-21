from datetime import datetime, timezone
from typing import Any

from app.models.ticket import Ticket
from app.storage.sqlite import SQLiteDatabase


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TicketRepository:
    def __init__(self, db: SQLiteDatabase) -> None:
        self.db = db

    def count_today_tickets(self, utc_day_start: str, utc_day_end: str) -> int:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) FROM tickets
                WHERE created_at_utc >= ? AND created_at_utc < ?
                AND status != 'preview' AND ticket_code != ''
                """,
                (utc_day_start, utc_day_end),
            ).fetchone()
            return row[0]

    def create(
        self,
        ticket_code: str,
        source_type: str,
        user_id: int,
        username: str | None,
        first_name: str | None,
        user_chat_id: int,
        user_message_id: int,
        user_message_thread_id: int | None,
        user_message_text: str | None,
        status: str = "new",
    ) -> "Ticket":
        now = _utc_now()
        with self.db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO tickets (
                    ticket_code, status, source_type, user_id, username, first_name,
                    user_chat_id, user_message_id, user_message_thread_id,
                    user_message_text, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket_code, status, source_type, user_id, username, first_name,
                    user_chat_id, user_message_id, user_message_thread_id,
                    user_message_text, now,
                ),
            )
            ticket_id = int(cursor.lastrowid)
        return self.get_by_id(ticket_id)  # type: ignore[return-value]

    def set_ticket_code(self, ticket_id: int, ticket_code: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE tickets SET ticket_code = ? WHERE id = ?",
                (ticket_code, ticket_id),
            )

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
                WHERE id = ? AND status IN ('new', 'preview')
                """,
                (_utc_now(), reacted_by, ticket_id),
            )

    def mark_answered(self, ticket_id: int, answer_message_id: int) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE tickets
                SET status = 'answered', answered_at_utc = ?, answer_message_id = ?
                WHERE id = ? AND status IN ('new', 'reacted', 'answered')
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

    def set_sheets_row_number(self, ticket_id: int, row_number: int) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE tickets SET sheets_row_number = ? WHERE id = ?",
                (row_number, ticket_id),
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

    def track_message(self, ticket_id: int, msg_type: str, message_id: int) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO ticket_messages
                    (ticket_id, msg_type, support_group_message_id, created_at_utc)
                VALUES (?, ?, ?, ?)
                """,
                (ticket_id, msg_type, message_id, _utc_now()),
            )

    def get_ticket_by_any_message(self, message_id: int) -> Ticket | None:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT t.* FROM tickets t
                JOIN ticket_messages tm ON t.id = tm.ticket_id
                WHERE tm.support_group_message_id = ?
                """,
                (message_id,),
            ).fetchone()
            return Ticket(dict(row)) if row else None

    def get_all_support_message_ids(self, ticket_id: int) -> list[int]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT support_group_message_id FROM ticket_messages WHERE ticket_id = ?",
                (ticket_id,),
            ).fetchall()
            return [r[0] for r in rows]

    def get_user_reply_ids(self, ticket_id: int) -> list[int]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT support_group_message_id FROM ticket_messages
                WHERE ticket_id = ? AND msg_type = 'user_reply'
                """,
                (ticket_id,),
            ).fetchall()
            return [r[0] for r in rows]

    def get_answer_delivered_ids(self, ticket_id: int) -> list[int]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT support_group_message_id FROM ticket_messages
                WHERE ticket_id = ? AND msg_type = 'answer_delivered'
                """,
                (ticket_id,),
            ).fetchall()
            return [r[0] for r in rows]

    def get_open_direct_by_dm_topic(self, user_chat_id: int, topic_id: int) -> Ticket | None:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM tickets
                WHERE source_type = 'direct'
                AND user_chat_id = ?
                AND user_message_thread_id = ?
                AND status != 'closed'
                ORDER BY id DESC LIMIT 1
                """,
                (user_chat_id, topic_id),
            ).fetchone()
            return Ticket(dict(row)) if row else None

    def get_previews_for_user(self, user_id: int, user_chat_id: int, exclude_id: int) -> list["Ticket"]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM tickets
                WHERE user_id = ? AND user_chat_id = ? AND status = 'preview' AND id != ?
                ORDER BY id
                """,
                (user_id, user_chat_id, exclude_id),
            ).fetchall()
            return [Ticket(dict(r)) for r in rows]

    def close_preview(self, ticket_id: int) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE tickets SET status = 'closed', closed_at_utc = ? WHERE id = ? AND status = 'preview'",
                (_utc_now(), ticket_id),
            )

    def get_open_for_user(self, user_id: int, user_chat_id: int) -> Ticket | None:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM tickets
                WHERE user_id = ? AND user_chat_id = ? AND status != 'closed'
                ORDER BY id DESC LIMIT 1
                """,
                (user_id, user_chat_id),
            ).fetchone()
            return Ticket(dict(row)) if row else None

    def get_unsync_closed(self, limit: int = 50) -> list[Ticket]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tickets WHERE status = 'closed' AND sheets_synced = 0 ORDER BY id LIMIT ?",
                (limit,),
            ).fetchall()
            return [Ticket(dict(r)) for r in rows]
