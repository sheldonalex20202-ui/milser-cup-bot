from app.models.ticket import Ticket
from app.services.ticket import TicketService


def make_service() -> TicketService:
    class Sender:
        def send_message(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("direct tickets must not send bot messages to the user")

        def copy_message(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("direct tickets must not copy bot media to the user")

        def send_sticker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("direct tickets must not send bot stickers to the user")

    return TicketService(
        tickets=object(),  # type: ignore[arg-type]
        sender=Sender(),  # type: ignore[arg-type]
        sheets=object(),  # type: ignore[arg-type]
        support_group_chat_id=-1001,
        support_topic_warnings=256,
        support_admin_user_ids=[],
    )


def make_direct_ticket() -> Ticket:
    return Ticket(
        {
            "id": 1,
            "ticket_code": "D0105-15",
            "status": "reacted",
            "source_type": "direct",
            "user_id": 100,
            "user_chat_id": -2072265469576,
            "user_message_id": 50,
            "user_message_thread_id": None,
            "user_direct_messages_topic_id": 123456,
            "created_at_utc": "2026-05-01T10:00:00+00:00",
        }
    )


def test_direct_tickets_do_not_send_bot_messages_to_user() -> None:
    service = make_service()
    ticket = make_direct_ticket()

    assert service._safe_send_to_user(ticket, "accepted") is None
    assert service._copy_media_to_user(ticket, {"message_id": 10}) is None
    assert service._send_sticker_to_user(ticket, "sticker-id") is None


def test_direct_delivery_kwargs_can_still_restore_existing_topic_context() -> None:
    ticket = Ticket(
        {
            "id": 1,
            "ticket_code": "D0105-15",
            "status": "reacted",
            "source_type": "direct",
            "user_id": 100,
            "user_chat_id": -2072265469576,
            "user_message_id": 50,
            "user_message_thread_id": None,
            "user_direct_messages_topic_id": 123456,
            "created_at_utc": "2026-05-01T10:00:00+00:00",
        }
    )

    assert make_service()._user_delivery_kwargs(ticket) == {"message_thread_id": 123456}


def test_ticket_list_command_does_not_require_admin_ids() -> None:
    update = {
        "message": {
            "chat": {"id": -1001},
            "from": {"id": 999},
            "message_thread_id": 256,
            "text": "/tickets",
        }
    }

    assert make_service().is_ticket_list_command(update)


def test_ticket_list_command_works_in_any_support_topic() -> None:
    update = {
        "message": {
            "chat": {"id": -1001},
            "from": {"id": 999},
            "message_thread_id": 999999,
            "text": "/tickets@mixer_bot",
        }
    }

    assert make_service().is_ticket_list_command(update)


def test_ticket_list_command_still_requires_support_group() -> None:
    update = {
        "message": {
            "chat": {"id": -2002},
            "from": {"id": 999},
            "message_thread_id": 999999,
            "text": "/tickets",
        }
    }

    assert not make_service().is_ticket_list_command(update)


def test_ticket_list_command_accepts_matching_warnings_topic_even_if_chat_id_differs() -> None:
    update = {
        "message": {
            "chat": {"id": -2002},
            "from": {"id": 999},
            "message_thread_id": 256,
            "text": "/tickets",
        }
    }

    assert make_service().is_ticket_list_command(update)


def test_ticket_list_command_ignores_messages_without_text() -> None:
    updates = [
        {"message": {"chat": {"id": -1001}, "message_thread_id": 256}},
        {"message": {"chat": {"id": -1001}, "message_thread_id": 256, "text": ""}},
        {"message": {"chat": {"id": -1001}, "message_thread_id": 256, "caption": ""}},
    ]

    for update in updates:
        assert not make_service().is_ticket_list_command(update)


def test_repeated_react_callback_repairs_stale_button() -> None:
    class Sender:
        def __init__(self) -> None:
            self.reply_markup_edits = []

        def edit_message_reply_markup(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            self.reply_markup_edits.append((args, kwargs))
            return {"ok": True}

        def answer_callback_query(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            return {"ok": True}

    sender = Sender()
    service = TicketService(
        tickets=object(),  # type: ignore[arg-type]
        sender=sender,  # type: ignore[arg-type]
        sheets=object(),  # type: ignore[arg-type]
        support_group_chat_id=-1001,
    )
    ticket = Ticket(
        {
            "id": 1,
            "ticket_code": "D1505-11",
            "status": "reacted",
            "source_type": "comment",
            "user_id": 100,
            "user_chat_id": -2002,
            "user_message_id": 50,
            "user_message_thread_id": 3000,
            "support_group_message_id": 9001,
            "created_at_utc": "2026-05-15T12:00:00+00:00",
        }
    )

    service._handle_react(ticket, "callback-id", caller_id=500)

    assert len(sender.reply_markup_edits) == 1
    args, _kwargs = sender.reply_markup_edits[0]
    assert args[0] == -1001
    assert args[1] == 9001
    assert args[2]["inline_keyboard"][0][0]["text"] == "✅ Отреагировано"


def test_support_message_falls_back_to_group_root_when_topic_send_fails() -> None:
    class Sender:
        def __init__(self) -> None:
            self.calls = []

        def send_message(self, **kwargs):  # noqa: ANN003, ANN202
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                raise RuntimeError("message thread not found")
            return {"ok": True, "result": {"message_id": 777}}

    sender = Sender()
    service = TicketService(
        tickets=object(),  # type: ignore[arg-type]
        sender=sender,  # type: ignore[arg-type]
        sheets=object(),  # type: ignore[arg-type]
        support_group_chat_id=-1001,
        support_topic_comments=123,
    )

    result = service._send_support_message(text="ticket", source_type="comment")

    assert result["result"]["message_id"] == 777
    assert sender.calls[0]["message_thread_id"] == 123
    assert sender.calls[1]["message_thread_id"] is None


def test_support_message_falls_back_without_reply_when_original_card_is_unavailable() -> None:
    class Sender:
        def __init__(self) -> None:
            self.calls = []

        def send_message(self, **kwargs):  # noqa: ANN003, ANN202
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                raise RuntimeError("reply message not found")
            return {"ok": True, "result": {"message_id": 778}}

    sender = Sender()
    service = TicketService(
        tickets=object(),  # type: ignore[arg-type]
        sender=sender,  # type: ignore[arg-type]
        sheets=object(),  # type: ignore[arg-type]
        support_group_chat_id=-1001,
        support_topic_direct=456,
    )

    result = service._send_support_message(
        text="continuation",
        source_type="direct",
        reply_to_message_id=9001,
    )

    assert result["result"]["message_id"] == 778
    assert sender.calls[0]["reply_to_message_id"] == 9001
    assert sender.calls[0]["message_thread_id"] == 456
    assert sender.calls[1]["reply_to_message_id"] is None
    assert sender.calls[1]["message_thread_id"] == 456


def test_matching_direct_broadcast_message_is_not_counted_as_ticket_answer() -> None:
    class Tickets:
        def __init__(self) -> None:
            self.consumed = []

        def consume_direct_broadcast_suppression(self, *args):  # noqa: ANN002, ANN202
            self.consumed.append(args)
            return True

        def get_open_direct_by_dm_topic(self, *args):  # noqa: ANN002, ANN202
            raise AssertionError("suppressed broadcast must not load ticket")

    class Sender:
        def send_message(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise AssertionError("suppressed broadcast must not send support notification")

    tickets = Tickets()
    service = TicketService(
        tickets=tickets,  # type: ignore[arg-type]
        sender=Sender(),  # type: ignore[arg-type]
        sheets=object(),  # type: ignore[arg-type]
        support_group_chat_id=-1001,
    )

    service.handle_community_dm_reply(
        {
            "message_id": 2000,
            "chat": {"id": -2002},
            "direct_messages_topic": {"topic_id": 3000},
            "sender_chat": {"id": -2002},
            "text": "broadcast",
        }
    )

    assert tickets.consumed == [(-2002, 3000, 2000)]


def test_direct_reply_is_ignored_when_ticket_is_not_waiting_for_answer() -> None:
    class Tickets:
        def consume_direct_broadcast_suppression(self, *args):  # noqa: ANN002, ANN202
            return False

        def get_open_direct_by_dm_topic(self, *args):  # noqa: ANN002, ANN202
            return Ticket(
                {
                    "id": 1,
                    "ticket_code": "D0105-15",
                    "status": "new",
                    "source_type": "direct",
                    "user_id": 100,
                    "user_chat_id": -2002,
                    "user_message_id": 50,
                    "user_message_thread_id": None,
                    "user_direct_messages_topic_id": 3000,
                    "created_at_utc": "2026-05-01T10:00:00+00:00",
                }
            )

    class Sender:
        def send_message(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise AssertionError("new direct ticket must not be marked answered")

    service = TicketService(
        tickets=Tickets(),  # type: ignore[arg-type]
        sender=Sender(),  # type: ignore[arg-type]
        sheets=object(),  # type: ignore[arg-type]
        support_group_chat_id=-1001,
    )

    service.handle_community_dm_reply(
        {
            "message_id": 2001,
            "chat": {"id": -2002},
            "direct_messages_topic": {"topic_id": 3000},
            "sender_chat": {"id": -2002},
            "text": "not a ticket answer",
        }
    )
