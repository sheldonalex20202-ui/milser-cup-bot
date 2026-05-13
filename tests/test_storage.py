from pathlib import Path
from uuid import uuid4
from datetime import datetime, timedelta, timezone

from app.models.domain import ContentType, NormalizedMessage, SourceType
from app.sheets.rows import build_messages_row
from app.sheets.ticket_rows import build_initial_ticket_row, _fmt_time
from app.storage.sqlite import DuplicateEventError, IngestEventRepository, SQLiteDatabase
from app.storage.tickets import TicketRepository


def make_message(update_id: int = 1, message_id: int = 2) -> NormalizedMessage:
    return NormalizedMessage(
        source_type=SourceType.DIRECT,
        telegram_update_id=update_id,
        telegram_message_id=message_id,
        telegram_chat_id=3,
        user_id=4,
        message_date_utc="2023-11-14T22:13:20+00:00",
        content_type=ContentType.TEXT,
        text="hello",
        raw_update_json={"update_id": update_id},
        raw_message_json={"message_id": message_id},
    )


def runtime_db() -> SQLiteDatabase:
    path = Path("test-data") / uuid4().hex / "app.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return SQLiteDatabase(path)


def test_create_pending_and_dedupe_by_update_id():
    db = runtime_db()
    db.initialize()
    repo = IngestEventRepository(db)
    message = make_message()

    event_id = repo.create_pending(message, build_messages_row(message))

    assert event_id == 1
    try:
        repo.create_pending(make_message(update_id=1, message_id=99), build_messages_row(message))
    except DuplicateEventError:
        pass
    else:
        raise AssertionError("expected DuplicateEventError")


def test_pending_event_can_be_marked_synced():
    db = runtime_db()
    db.initialize()
    repo = IngestEventRepository(db)
    message = make_message()
    event_id = repo.create_pending(message, build_messages_row(message))

    pending = repo.get_pending(limit=10)
    repo.mark_synced(event_id)

    assert len(pending) == 1
    assert repo.get_pending(limit=10) == []


def test_comment_preview_is_not_active_ticket_and_does_not_alert():
    db = runtime_db()
    db.initialize()
    repo = TicketRepository(db)
    preview = repo.create(
        ticket_code="",
        status="preview",
        source_type="comment",
        user_id=1,
        username=None,
        first_name=None,
        user_chat_id=10,
        user_message_id=20,
        user_message_thread_id=30,
        user_message_text="comment noise",
    )
    repo.set_support_message(preview.id, 1000)
    old_time = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    with db.connect() as conn:
        conn.execute("UPDATE tickets SET created_at_utc = ? WHERE id = ?", (old_time, preview.id))

    assert repo.get_active_tickets() == []
    assert repo.get_stale_tickets(threshold_seconds=60, repeat_seconds=120) == []


def test_mark_answered_also_sets_primary_reaction_when_missing():
    db = runtime_db()
    db.initialize()
    repo = TicketRepository(db)
    ticket = repo.create(
        ticket_code="D0305-01",
        source_type="direct",
        user_id=1,
        username=None,
        first_name=None,
        user_chat_id=10,
        user_message_id=20,
        user_message_thread_id=30,
        user_message_text="question",
    )

    repo.mark_answered(ticket.id, answer_message_id=2000)
    ticket = repo.get_by_id(ticket.id)

    assert ticket is not None
    assert ticket.status == "answered"
    assert ticket.reacted_at_utc
    assert ticket.answered_at_utc


def test_direct_broadcast_suppression_is_set_only_for_reacted_direct_ticket():
    db = runtime_db()
    db.initialize()
    repo = TicketRepository(db)
    new_ticket = repo.create(
        ticket_code="D0305-01",
        source_type="direct",
        user_id=1,
        username=None,
        first_name=None,
        user_chat_id=10,
        user_message_id=20,
        user_message_thread_id=30,
        user_message_text="question",
    )

    assert repo.mark_direct_broadcast_suppressed(10, 30, 2000) is False

    repo.mark_reacted(new_ticket.id, reacted_by=99)

    assert repo.mark_direct_broadcast_suppressed(10, 30, 2000) is True
    assert repo.consume_direct_broadcast_suppression(10, 30, 2000) is True
    assert repo.consume_direct_broadcast_suppression(10, 30, 2000) is False


def test_ticket_time_formatter_accepts_postgres_datetime():
    assert _fmt_time(datetime(2026, 4, 30, 17, 0, tzinfo=timezone.utc), 3) == "20:00"


def test_ticket_sheet_row_uses_telegram_message_time():
    db = runtime_db()
    db.initialize()
    repo = TicketRepository(db)
    ticket = repo.create(
        ticket_code="D1305-01",
        source_type="direct",
        user_id=1,
        username="alice",
        first_name=None,
        user_chat_id=10,
        user_message_id=20,
        user_message_thread_id=30,
        user_message_text="open issue",
        user_message_date_utc="2026-05-13T11:27:13+00:00",
    )

    row = build_initial_ticket_row(ticket, tz_offset=3)

    assert row[5] == "14:27"
