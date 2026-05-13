from datetime import datetime, timedelta, timezone
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

    def next_ticket_code(
        self,
        counter_key: str,
        shift: str,
        shift_start_utc: str,
        shift_end_utc: str,
    ) -> str:
        now = _utc_now()
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO ticket_counters (
                    counter_key, shift, shift_start_utc, shift_end_utc, last_seq, updated_at_utc
                )
                VALUES (?, ?, ?, ?, 0, ?)
                """,
                (counter_key, shift, shift_start_utc, shift_end_utc, now),
            )
            row = conn.execute(
                """
                UPDATE ticket_counters
                SET last_seq = last_seq + 1, updated_at_utc = ?
                WHERE counter_key = ?
                RETURNING last_seq
                """,
                (now, counter_key),
            ).fetchone()
            seq = int(row["last_seq"])
        return f"{counter_key}-{seq:02d}"

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
        user_message_date_utc: str | None = None,
    ) -> "Ticket":
        now = _utc_now()
        message_date = user_message_date_utc or now
        with self.db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO tickets (
                    ticket_code, status, source_type, user_id, username, first_name,
                    user_chat_id, user_message_id, user_message_thread_id,
                    user_message_date_utc, user_message_text, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket_code, status, source_type, user_id, username, first_name,
                    user_chat_id, user_message_id, user_message_thread_id,
                    message_date, user_message_text, now,
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
        now = _utc_now()
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE tickets
                SET status = 'answered',
                    reacted_at_utc = COALESCE(reacted_at_utc, ?),
                    answered_at_utc = ?,
                    answer_message_id = ?
                WHERE id = ? AND status IN ('new', 'reacted', 'answered')
                """,
                (now, now, answer_message_id, ticket_id),
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

    def purge_closed_synced(self, limit: int = 100) -> int:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT id FROM tickets
                WHERE status = 'closed' AND sheets_synced = 1
                ORDER BY id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            ticket_ids = [int(row["id"]) for row in rows]
            if not ticket_ids:
                return 0
            placeholders = ",".join("?" for _ in ticket_ids)
            conn.execute(f"DELETE FROM ticket_alerts WHERE ticket_id IN ({placeholders})", ticket_ids)
            conn.execute(f"DELETE FROM ticket_messages WHERE ticket_id IN ({placeholders})", ticket_ids)
            conn.execute(f"DELETE FROM tickets WHERE id IN ({placeholders})", ticket_ids)
            return len(ticket_ids)

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

    def mark_direct_broadcast_suppressed(
        self,
        user_chat_id: int,
        topic_id: int,
        message_id: int,
        ttl_seconds: int = 600,
    ) -> bool:
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()
        with self.db.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE tickets
                SET suppressed_direct_message_id = ?,
                    suppressed_direct_until_utc = ?
                WHERE id = (
                    SELECT id FROM tickets
                    WHERE source_type = 'direct'
                      AND user_chat_id = ?
                      AND user_message_thread_id = ?
                      AND status = 'reacted'
                    ORDER BY id DESC
                    LIMIT 1
                )
                """,
                (message_id, expires_at, user_chat_id, topic_id),
            )
            return cursor.rowcount > 0

    def consume_direct_broadcast_suppression(
        self,
        user_chat_id: int,
        topic_id: int,
        message_id: int,
    ) -> bool:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM tickets
                WHERE source_type = 'direct'
                  AND user_chat_id = ?
                  AND user_message_thread_id = ?
                  AND suppressed_direct_message_id = ?
                  AND suppressed_direct_until_utc IS NOT NULL
                  AND datetime(suppressed_direct_until_utc) >= datetime('now')
                ORDER BY id DESC
                LIMIT 1
                """,
                (user_chat_id, topic_id, message_id),
            ).fetchone()
            if not row:
                return False
            conn.execute(
                """
                UPDATE tickets
                SET suppressed_direct_message_id = NULL,
                    suppressed_direct_until_utc = NULL
                WHERE id = ?
                """,
                (row["id"],),
            )
            return True

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
                """
                UPDATE tickets
                SET status = 'closed', closed_at_utc = ?, sheets_synced = 1
                WHERE id = ? AND status = 'preview'
                """,
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

    def get_open_panel_tickets(self, limit: int = 300) -> list[Ticket]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM tickets
                WHERE status NOT IN ('preview', 'closed') AND ticket_code != ''
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [Ticket(dict(r)) for r in rows]

    def get_active_tickets(self, limit: int = 100) -> list[Ticket]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tickets WHERE status NOT IN ('preview', 'closed') ORDER BY id LIMIT ?",
                (limit,),
            ).fetchall()
            return [Ticket(dict(r)) for r in rows]

    def get_stale_tickets(
        self,
        threshold_seconds: int,
        repeat_seconds: int = 1800,
        limit: int = 50,
    ) -> list[tuple[Ticket, str]]:
        rows: list[tuple[Ticket, str]] = []
        with self.db.connect() as conn:
            cursor = conn.execute(
                """
                SELECT t.*, 'primary_reaction' AS alert_type
                FROM tickets t
                WHERE t.status = 'new'
                  AND t.support_group_message_id IS NOT NULL
                  AND datetime(t.created_at_utc) <= datetime('now', '-' || ? || ' seconds')
                  AND NOT EXISTS (
                      SELECT 1 FROM ticket_alerts a
                      WHERE a.ticket_id = t.id AND a.alert_type = 'primary_reaction'
                        AND datetime(a.sent_at_utc) > datetime('now', '-' || ? || ' seconds')
                  )
                ORDER BY t.id
                LIMIT ?
                """,
                (threshold_seconds, repeat_seconds, limit),
            )
            rows.extend((Ticket(dict(r)), str(r["alert_type"])) for r in cursor.fetchall())
            remaining = max(limit - len(rows), 0)
            if remaining:
                cursor = conn.execute(
                    """
                    SELECT t.*, 'secondary_reaction' AS alert_type
                    FROM tickets t
                    WHERE t.status = 'reacted'
                      AND t.support_group_message_id IS NOT NULL
                      AND t.reacted_at_utc IS NOT NULL
                      AND datetime(t.reacted_at_utc) <= datetime('now', '-' || ? || ' seconds')
                      AND NOT EXISTS (
                          SELECT 1 FROM ticket_alerts a
                          WHERE a.ticket_id = t.id AND a.alert_type = 'secondary_reaction'
                            AND datetime(a.sent_at_utc) > datetime('now', '-' || ? || ' seconds')
                      )
                    ORDER BY t.id
                    LIMIT ?
                    """,
                    (threshold_seconds, repeat_seconds, remaining),
                )
                rows.extend((Ticket(dict(r)), str(r["alert_type"])) for r in cursor.fetchall())
            remaining = max(limit - len(rows), 0)
            if remaining:
                cursor = conn.execute(
                    """
                    SELECT t.*, 'close' AS alert_type
                    FROM tickets t
                    WHERE t.status = 'answered'
                      AND t.support_group_message_id IS NOT NULL
                      AND t.answered_at_utc IS NOT NULL
                      AND datetime(t.answered_at_utc) <= datetime('now', '-' || ? || ' seconds')
                      AND NOT EXISTS (
                          SELECT 1 FROM ticket_alerts a
                          WHERE a.ticket_id = t.id AND a.alert_type = 'close'
                            AND datetime(a.sent_at_utc) > datetime('now', '-' || ? || ' seconds')
                      )
                    ORDER BY t.id
                    LIMIT ?
                    """,
                    (threshold_seconds, repeat_seconds, remaining),
                )
                rows.extend((Ticket(dict(r)), str(r["alert_type"])) for r in cursor.fetchall())
        return rows

    def record_ticket_alert(self, ticket_id: int, alert_type: str, support_group_message_id: int | None) -> bool:
        with self.db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO ticket_alerts (
                    ticket_id, alert_type, sent_at_utc, support_group_message_id
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(ticket_id, alert_type) DO UPDATE SET
                    sent_at_utc = excluded.sent_at_utc,
                    support_group_message_id = excluded.support_group_message_id
                """,
                (ticket_id, alert_type, _utc_now(), support_group_message_id),
            )
            return cursor.rowcount > 0

    def get_without_sheets_row(self, limit: int = 50) -> list[Ticket]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM tickets
                WHERE ticket_code != '' AND sheets_row_number IS NULL
                ORDER BY id LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [Ticket(dict(r)) for r in rows]
