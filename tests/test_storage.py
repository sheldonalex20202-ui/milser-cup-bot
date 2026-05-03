from pathlib import Path
from uuid import uuid4
from datetime import datetime, timedelta, timezone

from app.models.domain import ContentType, NormalizedMessage, SourceType
from app.sheets.rows import build_messages_row
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
