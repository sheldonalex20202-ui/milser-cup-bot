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
