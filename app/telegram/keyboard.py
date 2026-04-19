from typing import Any


def react_keyboard(ticket_id: int) -> dict[str, Any]:
    return {"inline_keyboard": [[{"text": "⚡ Отреагировать", "callback_data": f"react:{ticket_id}"}]]}


def close_keyboard(ticket_id: int) -> dict[str, Any]:
    return {"inline_keyboard": [[{"text": "✅ Закрыть тикет", "callback_data": f"close:{ticket_id}"}]]}


def reacted_keyboard() -> dict[str, Any]:
    return {"inline_keyboard": [[{"text": "✅ Отреагировано", "callback_data": "noop"}]]}


def closed_keyboard() -> dict[str, Any]:
    return {"inline_keyboard": [[{"text": "🔒 Тикет закрыт", "callback_data": "noop"}]]}


def parse_callback_data(data: str) -> tuple[str, int] | None:
    """Return (action, ticket_id) or None if unrecognized."""
    if data == "noop":
        return "noop", 0
    try:
        action, raw_id = data.split(":", 1)
        if action in ("react", "close"):
            return action, int(raw_id)
    except (ValueError, AttributeError):
        pass
    return None
