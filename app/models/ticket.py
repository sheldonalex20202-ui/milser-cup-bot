from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class TicketStatus(StrEnum):
    PREVIEW = "preview"  # comment message waiting for admin reaction
    NEW = "new"
    REACTED = "reacted"
    ANSWERED = "answered"
    CLOSED = "closed"


class Ticket:
    """Mutable ticket object hydrated from SQLite rows."""

    __slots__ = (
        "id",
        "ticket_code",
        "status",
        "source_type",
        "user_id",
        "username",
        "first_name",
        "user_chat_id",
        "user_message_id",
        "user_message_thread_id",
        "user_direct_messages_topic_id",
        "user_message_text",
        "support_group_message_id",
        "answer_message_id",
        "created_at_utc",
        "reacted_at_utc",
        "reacted_by_user_id",
        "answered_at_utc",
        "closed_at_utc",
        "closed_by_user_id",
        "sheets_synced",
        "sheets_row_number",
        "suppressed_direct_message_id",
        "suppressed_direct_until_utc",
    )

    def __init__(self, row: dict[str, Any]) -> None:
        self.id: int = row["id"]
        self.ticket_code: str = row["ticket_code"]
        self.status: str = row["status"]
        self.source_type: str = row["source_type"]
        self.user_id: int = row["user_id"]
        self.username: str | None = row.get("username")
        self.first_name: str | None = row.get("first_name")
        self.user_chat_id: int = row["user_chat_id"]
        self.user_message_id: int = row["user_message_id"]
        self.user_message_thread_id: int | None = row.get("user_message_thread_id")
        self.user_direct_messages_topic_id: int | None = row.get("user_direct_messages_topic_id")
        self.user_message_text: str | None = row.get("user_message_text")
        self.support_group_message_id: int | None = row.get("support_group_message_id")
        self.answer_message_id: int | None = row.get("answer_message_id")
        self.created_at_utc: str = row["created_at_utc"]
        self.reacted_at_utc: str | None = row.get("reacted_at_utc")
        self.reacted_by_user_id: int | None = row.get("reacted_by_user_id")
        self.answered_at_utc: str | None = row.get("answered_at_utc")
        self.closed_at_utc: str | None = row.get("closed_at_utc")
        self.closed_by_user_id: int | None = row.get("closed_by_user_id")
        self.sheets_synced: int = row.get("sheets_synced", 0)
        self.sheets_row_number: int | None = row.get("sheets_row_number")
        self.suppressed_direct_message_id: int | None = row.get("suppressed_direct_message_id")
        self.suppressed_direct_until_utc: str | None = row.get("suppressed_direct_until_utc")

    @property
    def display_name(self) -> str:
        if self.username:
            return f"@{self.username}"
        return self.first_name or f"user#{self.user_id}"

    def reaction_seconds(self) -> int | None:
        if self.reacted_at_utc and self.created_at_utc:
            return _diff_seconds(self.created_at_utc, self.reacted_at_utc)
        return None

    def answer_seconds(self) -> int | None:
        if self.answered_at_utc and self.created_at_utc:
            return _diff_seconds(self.created_at_utc, self.answered_at_utc)
        return None

    def resolution_seconds(self) -> int | None:
        if self.closed_at_utc and self.created_at_utc:
            return _diff_seconds(self.created_at_utc, self.closed_at_utc)
        return None


def _diff_seconds(start_iso: str, end_iso: str) -> int:
    fmt = "%Y-%m-%dT%H:%M:%S.%f%z"

    def parse(s: str) -> datetime:
        for f in (fmt, "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(s, f)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue
        raise ValueError(f"Cannot parse datetime: {s}")

    return max(0, int((parse(end_iso) - parse(start_iso)).total_seconds()))
