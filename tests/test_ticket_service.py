from app.models.ticket import Ticket
from app.services.ticket import TicketService


def make_service() -> TicketService:
    return TicketService(
        tickets=object(),  # type: ignore[arg-type]
        sender=object(),  # type: ignore[arg-type]
        sheets=object(),  # type: ignore[arg-type]
        support_group_chat_id=-1001,
        support_topic_warnings=256,
        support_admin_user_ids=[],
    )


def test_direct_delivery_uses_direct_messages_topic_id() -> None:
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
