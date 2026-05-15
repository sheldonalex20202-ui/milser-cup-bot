from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

from app.api.tickets_ui import build_support_message_url, build_ticket_payload, render_ticket_panel_ui
from app.services.ticket import TicketService
from app.storage.sqlite import SQLiteDatabase
from app.storage.tickets import TicketRepository


def runtime_db() -> SQLiteDatabase:
    path = Path("test-data") / uuid4().hex / "app.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return SQLiteDatabase(path)


class Sender:
    def __init__(self) -> None:
        self.edits = []

    def edit_message_reply_markup(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        self.edits.append((args, kwargs))
        return {"ok": True}


def test_ticket_panel_lists_only_real_open_tickets() -> None:
    db = runtime_db()
    db.initialize()
    repo = TicketRepository(db)
    open_ticket = repo.create(
        ticket_code="D1205-01",
        source_type="direct",
        user_id=1,
        username="alice",
        first_name=None,
        user_chat_id=10,
        user_message_id=20,
        user_message_thread_id=30,
        user_message_text="open issue",
    )
    repo.create(
        ticket_code="",
        status="preview",
        source_type="comment",
        user_id=2,
        username=None,
        first_name="Bob",
        user_chat_id=11,
        user_message_id=21,
        user_message_thread_id=31,
        user_message_text="preview",
    )
    closed = repo.create(
        ticket_code="D1205-02",
        source_type="direct",
        user_id=3,
        username=None,
        first_name="Eve",
        user_chat_id=12,
        user_message_id=22,
        user_message_thread_id=32,
        user_message_text="closed",
    )
    repo.mark_closed(closed.id, closed_by=99)

    assert [ticket.id for ticket in repo.get_open_panel_tickets()] == [open_ticket.id]


def test_close_from_panel_closes_ticket_and_updates_markup() -> None:
    db = runtime_db()
    db.initialize()
    repo = TicketRepository(db)
    ticket = repo.create(
        ticket_code="D1205-01",
        source_type="direct",
        user_id=1,
        username="alice",
        first_name=None,
        user_chat_id=10,
        user_message_id=20,
        user_message_thread_id=30,
        user_message_text="open issue",
    )
    repo.set_support_message(ticket.id, 1000)
    repo.track_message(ticket.id, "answer_delivered", 2000)
    sender = Sender()
    service = TicketService(
        tickets=repo,
        sender=sender,  # type: ignore[arg-type]
        sheets=object(),  # type: ignore[arg-type]
        support_group_chat_id=-1001234567890,
    )

    closed = service.close_from_panel(ticket.id, closed_by=0)

    assert closed is not None
    assert closed.status == "closed"
    assert sender.edits
    assert repo.get_by_id(ticket.id) is None


def test_ticket_panel_payload_contains_private_group_link() -> None:
    db = runtime_db()
    db.initialize()
    repo = TicketRepository(db)
    ticket = repo.create(
        ticket_code="D1205-01",
        source_type="direct",
        user_id=1,
        username="alice",
        first_name=None,
        user_chat_id=10,
        user_message_id=20,
        user_message_thread_id=30,
        user_message_text="open issue",
    )
    repo.set_support_message(ticket.id, 456)
    ticket = repo.get_by_id(ticket.id)

    payload = build_ticket_payload(ticket, -1001234567890)  # type: ignore[arg-type]

    assert payload["support_url"] == "https://t.me/c/1234567890/456"
    assert build_support_message_url(-123, 456) is None
    html = render_ticket_panel_ui("secret")
    assert "Открытые тикеты" in html
    assert "box-shadow" not in html
    assert "closeQueue" in html
    assert "processCloseQueue" in html
    assert "while (closeQueue.length)" in html


def test_ticket_panel_payload_uses_telegram_message_time() -> None:
    db = runtime_db()
    db.initialize()
    repo = TicketRepository(db)
    message_time = datetime(2026, 5, 13, 11, 27, tzinfo=timezone.utc).isoformat()
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
        user_message_date_utc=message_time,
    )

    payload = build_ticket_payload(ticket, -1001234567890)

    assert payload["received_at_utc"] == message_time
    assert payload["received_at_utc"] != payload["created_at_utc"]
