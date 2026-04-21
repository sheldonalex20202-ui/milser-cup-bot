from typing import Any


def react_keyboard(ticket_id: int, dm_url: str | None = None) -> dict[str, Any]:
    rows: list[list[dict[str, Any]]] = [
        [{"text": "⚡ Отреагировать", "callback_data": f"react:{ticket_id}"}]
    ]
    if dm_url:
        rows.append([{"text": "💬 Ответить в директ", "url": dm_url}])
    return {"inline_keyboard": rows}


def close_keyboard(ticket_id: int, show_delete: bool = False) -> dict[str, Any]:
    rows: list[list[dict[str, Any]]] = [
        [{"text": "✅ Закрыть тикет", "callback_data": f"close:{ticket_id}"}]
    ]
    if show_delete:
        rows.append([{"text": "🗑 Удалить ответ пользователю", "callback_data": f"delete:{ticket_id}"}])
    return {"inline_keyboard": rows}


def reacted_keyboard(dm_url: str | None = None) -> dict[str, Any]:
    rows: list[list[dict[str, Any]]] = [
        [{"text": "✅ Отреагировано", "callback_data": "noop"}]
    ]
    if dm_url:
        rows.append([{"text": "💬 Ответить в директ", "url": dm_url}])
    return {"inline_keyboard": rows}


def deleted_keyboard() -> dict[str, Any]:
    return {"inline_keyboard": [[{"text": "✅ Удалено", "callback_data": "noop"}]]}


def closed_keyboard(ticket_id: int, show_delete: bool = False) -> dict[str, Any]:
    rows: list[list[dict[str, Any]]] = [
        [{"text": "🔒 Тикет закрыт", "callback_data": "noop"}]
    ]
    if show_delete:
        rows.append([{"text": "🗑 Удалить ответ пользователю", "callback_data": f"delete:{ticket_id}"}])
    return {"inline_keyboard": rows}


def parse_callback_data(data: str) -> tuple[str, int] | None:
    """Return (action, ticket_id) or None if unrecognized."""
    if data == "noop":
        return "noop", 0
    try:
        action, raw_id = data.split(":", 1)
        if action in ("react", "close", "delete"):
            return action, int(raw_id)
    except (ValueError, AttributeError):
        pass
    return None
