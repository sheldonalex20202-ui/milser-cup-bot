from datetime import datetime, timedelta, timezone
from typing import Any

from app.models.ticket import Ticket

TICKET_COLUMNS = [
    "КМ",
    "Код заявки",
    "Telegram Chat",
    "Telegram Direct",
    "Discord",
    "Время обращения",
    "Первичная реакция",
    "Вторичная реакция",
    "Время закрытия",
    "Сообщение",
]


def build_ticket_row(ticket: Ticket, tz_offset: int = 3) -> list[Any]:
    return [
        "",                                          # КМ
        ticket.ticket_code,                          # Код заявки
        "",                                          # Telegram Chat  (color set via API)
        "",                                          # Telegram Direct (color set via API)
        "",                                          # Discord         (color set via API)
        _fmt_time(ticket.created_at_utc, tz_offset),
        _fmt_time(ticket.reacted_at_utc, tz_offset),
        _fmt_time(ticket.answered_at_utc, tz_offset),
        _fmt_time(ticket.closed_at_utc, tz_offset),
        ticket.user_message_text or "",              # Сообщение
    ]


def _fmt_time(iso: str | None, tz_offset: int) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt + timedelta(hours=tz_offset)
        return local.strftime("%H:%M")
    except Exception:
        return iso or ""
