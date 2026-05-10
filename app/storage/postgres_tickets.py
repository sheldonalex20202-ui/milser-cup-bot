from typing import Any

from app.models.ticket import Ticket
from app.storage.postgres import PostgresDatabase


class PostgresTicketRepository:
    def __init__(self, db: PostgresDatabase) -> None:
        self.db = db

    def count_today_tickets(self, utc_day_start: str, utc_day_end: str) -> int:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                select count(*) as count from tickets
                where created_at_utc >= %s and created_at_utc < %s
                and status != 'preview' and ticket_code != ''
                """,
                (utc_day_start, utc_day_end),
            ).fetchone()
            return int(row["count"])

    def next_ticket_code(
        self,
        counter_key: str,
        shift: str,
        shift_start_utc: str,
        shift_end_utc: str,
    ) -> str:
        with self.db.connect() as conn:
            row = conn.execute(
                f"select {self.db.schema}.next_ticket_code(%s, %s, %s, %s) as ticket_code",
                (counter_key, shift, shift_start_utc, shift_end_utc),
            ).fetchone()
            return str(row["ticket_code"])

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
    ) -> Ticket:
        direct_topic_id = user_message_thread_id if source_type == "direct" else None
        thread_id = None if source_type == "direct" else user_message_thread_id
        with self.db.connect() as conn:
            row = conn.execute(
                """
                insert into tickets (
                    ticket_code, status, source_type, user_id, username, first_name,
                    user_chat_id, user_message_id, user_message_thread_id,
                    user_direct_messages_topic_id, user_message_text, created_at_utc
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                returning *
                """,
                (
                    ticket_code,
                    status,
                    source_type,
                    user_id,
                    username,
                    first_name,
                    user_chat_id,
                    user_message_id,
                    thread_id,
                    direct_topic_id,
                    user_message_text,
                ),
            ).fetchone()
            return Ticket(dict(row))

    def set_ticket_code(self, ticket_id: int, ticket_code: str) -> None:
        self._execute("update tickets set ticket_code = %s where id = %s", (ticket_code, ticket_id))

    def set_support_message(self, ticket_id: int, support_group_message_id: int) -> None:
        self._execute(
            "update tickets set support_group_message_id = %s where id = %s",
            (support_group_message_id, ticket_id),
        )

    def mark_reacted(self, ticket_id: int, reacted_by: int) -> None:
        self._execute(
            """
            update tickets
            set status = 'reacted', reacted_at_utc = now(), reacted_by_user_id = %s
            where id = %s and status in ('new', 'preview')
            """,
            (reacted_by, ticket_id),
        )

    def mark_answered(self, ticket_id: int, answer_message_id: int) -> None:
        self._execute(
            """
            update tickets
            set status = 'answered',
                reacted_at_utc = coalesce(reacted_at_utc, now()),
                answered_at_utc = now(),
                answer_message_id = %s
            where id = %s and status in ('new', 'reacted', 'answered')
            """,
            (answer_message_id, ticket_id),
        )

    def mark_closed(self, ticket_id: int, closed_by: int) -> None:
        self._execute(
            """
            update tickets
            set status = 'closed', closed_at_utc = now(), closed_by_user_id = %s
            where id = %s and status in ('new', 'reacted', 'answered')
            """,
            (closed_by, ticket_id),
        )

    def set_sheets_row_number(self, ticket_id: int, row_number: int) -> None:
        self._execute("update tickets set sheets_row_number = %s where id = %s", (row_number, ticket_id))

    def mark_sheets_synced(self, ticket_id: int) -> None:
        self._execute("update tickets set sheets_synced = true where id = %s", (ticket_id,))

    def purge_closed_synced(self, limit: int = 100) -> int:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                with deleted as (
                    delete from tickets
                    where id in (
                        select id from tickets
                        where status = 'closed' and sheets_synced = true
                        order by id
                        limit %s
                    )
                    returning id
                )
                select count(*) as count from deleted
                """,
                (limit,),
            ).fetchone()
            return int(row["count"])

    def get_by_id(self, ticket_id: int) -> Ticket | None:
        return self._one("select * from tickets where id = %s", (ticket_id,))

    def get_by_support_message(self, support_group_message_id: int) -> Ticket | None:
        return self._one("select * from tickets where support_group_message_id = %s", (support_group_message_id,))

    def track_message(self, ticket_id: int, msg_type: str, message_id: int) -> None:
        self._execute(
            """
            insert into ticket_messages (ticket_id, msg_type, support_group_message_id, created_at_utc)
            values (%s, %s, %s, now())
            on conflict (support_group_message_id) do nothing
            """,
            (ticket_id, msg_type, message_id),
        )

    def get_ticket_by_any_message(self, message_id: int) -> Ticket | None:
        return self._one(
            """
            select t.* from tickets t
            join ticket_messages tm on t.id = tm.ticket_id
            where tm.support_group_message_id = %s
            """,
            (message_id,),
        )

    def get_all_support_message_ids(self, ticket_id: int) -> list[int]:
        return self._ids("select support_group_message_id from ticket_messages where ticket_id = %s", (ticket_id,))

    def get_user_reply_ids(self, ticket_id: int) -> list[int]:
        return self._ids(
            """
            select support_group_message_id from ticket_messages
            where ticket_id = %s and msg_type = 'user_reply'
            """,
            (ticket_id,),
        )

    def get_answer_delivered_ids(self, ticket_id: int) -> list[int]:
        return self._ids(
            """
            select support_group_message_id from ticket_messages
            where ticket_id = %s and msg_type = 'answer_delivered'
            """,
            (ticket_id,),
        )

    def get_open_direct_by_dm_topic(self, user_chat_id: int, topic_id: int) -> Ticket | None:
        return self._one(
            """
            select * from tickets
            where source_type = 'direct'
            and user_chat_id = %s
            and user_direct_messages_topic_id = %s
            and status != 'closed'
            order by id desc limit 1
            """,
            (user_chat_id, topic_id),
        )

    def mark_direct_broadcast_suppressed(
        self,
        user_chat_id: int,
        topic_id: int,
        message_id: int,
        ttl_seconds: int = 600,
    ) -> bool:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                update tickets
                set suppressed_direct_message_id = %s,
                    suppressed_direct_until_utc = now() + (%s * interval '1 second')
                where id = (
                    select id from tickets
                    where source_type = 'direct'
                      and user_chat_id = %s
                      and user_direct_messages_topic_id = %s
                      and status = 'reacted'
                    order by id desc
                    limit 1
                )
                returning id
                """,
                (message_id, ttl_seconds, user_chat_id, topic_id),
            ).fetchone()
            return row is not None

    def consume_direct_broadcast_suppression(
        self,
        user_chat_id: int,
        topic_id: int,
        message_id: int,
    ) -> bool:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                update tickets
                set suppressed_direct_message_id = null,
                    suppressed_direct_until_utc = null
                where id = (
                    select id from tickets
                    where source_type = 'direct'
                      and user_chat_id = %s
                      and user_direct_messages_topic_id = %s
                      and suppressed_direct_message_id = %s
                      and suppressed_direct_until_utc >= now()
                    order by id desc
                    limit 1
                )
                returning id
                """,
                (user_chat_id, topic_id, message_id),
            ).fetchone()
            return row is not None

    def get_previews_for_user(self, user_id: int, user_chat_id: int, exclude_id: int) -> list[Ticket]:
        return self._many(
            """
            select * from tickets
            where user_id = %s and user_chat_id = %s and status = 'preview' and id != %s
            order by id
            """,
            (user_id, user_chat_id, exclude_id),
        )

    def close_preview(self, ticket_id: int) -> None:
        self._execute(
            """
            update tickets
            set status = 'closed', closed_at_utc = now(), sheets_synced = true
            where id = %s and status = 'preview'
            """,
            (ticket_id,),
        )

    def get_open_for_user(self, user_id: int, user_chat_id: int) -> Ticket | None:
        return self._one(
            """
            select * from tickets
            where user_id = %s and user_chat_id = %s and status != 'closed'
            order by id desc limit 1
            """,
            (user_id, user_chat_id),
        )

    def get_unsync_closed(self, limit: int = 50) -> list[Ticket]:
        return self._many(
            "select * from tickets where status = 'closed' and sheets_synced = false order by id limit %s",
            (limit,),
        )

    def get_without_sheets_row(self, limit: int = 50) -> list[Ticket]:
        return self._many(
            """
            select * from tickets
            where ticket_code <> '' and sheets_row_number is null
            order by id limit %s
            """,
            (limit,),
        )

    def get_active_tickets(self, limit: int = 100) -> list[Ticket]:
        return self._many(
            "select * from tickets where status not in ('preview', 'closed') order by id limit %s",
            (limit,),
        )

    def get_stale_tickets(
        self,
        threshold_seconds: int,
        repeat_seconds: int = 1800,
        limit: int = 50,
    ) -> list[tuple[Ticket, str]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                (
                    select t.*, 'primary_reaction' as alert_type
                    from tickets t
                    where t.status = 'new'
                      and t.support_group_message_id is not null
                      and t.created_at_utc <= now() - (%s * interval '1 second')
                      and not exists (
                          select 1 from ticket_alerts a
                          where a.ticket_id = t.id and a.alert_type = 'primary_reaction'
                            and a.sent_at_utc > now() - (%s * interval '1 second')
                      )
                    order by t.id
                    limit %s
                )
                union all
                (
                    select t.*, 'secondary_reaction' as alert_type
                    from tickets t
                    where t.status = 'reacted'
                      and t.support_group_message_id is not null
                      and t.reacted_at_utc is not null
                      and t.reacted_at_utc <= now() - (%s * interval '1 second')
                      and not exists (
                          select 1 from ticket_alerts a
                          where a.ticket_id = t.id and a.alert_type = 'secondary_reaction'
                            and a.sent_at_utc > now() - (%s * interval '1 second')
                      )
                    order by t.id
                    limit %s
                )
                union all
                (
                    select t.*, 'close' as alert_type
                    from tickets t
                    where t.status = 'answered'
                      and t.support_group_message_id is not null
                      and t.answered_at_utc is not null
                      and t.answered_at_utc <= now() - (%s * interval '1 second')
                      and not exists (
                          select 1 from ticket_alerts a
                          where a.ticket_id = t.id and a.alert_type = 'close'
                            and a.sent_at_utc > now() - (%s * interval '1 second')
                      )
                    order by t.id
                    limit %s
                )
                order by id
                limit %s
                """,
                (
                    threshold_seconds,
                    repeat_seconds,
                    limit,
                    threshold_seconds,
                    repeat_seconds,
                    limit,
                    threshold_seconds,
                    repeat_seconds,
                    limit,
                    limit,
                ),
            ).fetchall()
            return [(Ticket(dict(row)), str(row["alert_type"])) for row in rows]

    def record_ticket_alert(self, ticket_id: int, alert_type: str, support_group_message_id: int | None) -> bool:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                insert into ticket_alerts (ticket_id, alert_type, sent_at_utc, support_group_message_id)
                values (%s, %s, now(), %s)
                on conflict (ticket_id, alert_type) do update set
                    sent_at_utc = excluded.sent_at_utc,
                    support_group_message_id = excluded.support_group_message_id
                returning id
                """,
                (ticket_id, alert_type, support_group_message_id),
            ).fetchone()
            return row is not None

    def _execute(self, sql: str, params: tuple[Any, ...]) -> None:
        with self.db.connect() as conn:
            conn.execute(sql, params)

    def _one(self, sql: str, params: tuple[Any, ...]) -> Ticket | None:
        with self.db.connect() as conn:
            row = conn.execute(sql, params).fetchone()
            return Ticket(dict(row)) if row else None

    def _many(self, sql: str, params: tuple[Any, ...]) -> list[Ticket]:
        with self.db.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [Ticket(dict(row)) for row in rows]

    def _ids(self, sql: str, params: tuple[Any, ...]) -> list[int]:
        with self.db.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [int(row["support_group_message_id"]) for row in rows]
