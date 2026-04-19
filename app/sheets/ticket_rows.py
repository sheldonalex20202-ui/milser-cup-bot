from typing import Any

from app.models.ticket import Ticket

TICKET_COLUMNS = [
    "ticket_code",
    "status",
    "source_type",
    "user_id",
    "username",
    "first_name",
    "user_message_text",
    "created_at_utc",
    "reacted_at_utc",
    "answered_at_utc",
    "closed_at_utc",
    "reaction_time_sec",
    "answer_time_sec",
    "resolution_time_sec",
]


def build_ticket_row(ticket: Ticket) -> list[Any]:
    return [
        ticket.ticket_code,
        ticket.status,
        ticket.source_type,
        ticket.user_id,
        ticket.username or "",
        ticket.first_name or "",
        ticket.user_message_text or "",
        ticket.created_at_utc,
        ticket.reacted_at_utc or "",
        ticket.answered_at_utc or "",
        ticket.closed_at_utc or "",
        ticket.reaction_seconds() if ticket.reaction_seconds() is not None else "",
        ticket.answer_seconds() if ticket.answer_seconds() is not None else "",
        ticket.resolution_seconds() if ticket.resolution_seconds() is not None else "",
    ]
