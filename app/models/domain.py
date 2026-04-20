from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SourceType(StrEnum):
    COMMENT = "comment"
    DIRECT = "direct"


class ContentType(StrEnum):
    TEXT = "text"
    PHOTO = "photo"
    VIDEO = "video"
    DOCUMENT = "document"
    AUDIO = "audio"
    VOICE = "voice"
    VIDEO_NOTE = "video_note"
    STICKER = "sticker"
    ANIMATION = "animation"
    CONTACT = "contact"
    LOCATION = "location"
    POLL = "poll"
    OTHER = "other"


class NormalizedMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: SourceType
    telegram_update_id: int
    telegram_message_id: int
    telegram_chat_id: int
    telegram_message_thread_id: int | None = None
    telegram_direct_messages_topic_id: int | None = None
    channel_chat_id: int | None = None
    discussion_group_chat_id: int | None = None
    channel_post_id: int | None = None
    user_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    message_date_utc: datetime
    content_type: ContentType
    text: str | None = None
    caption: str | None = None
    media_json: dict[str, Any] = Field(default_factory=dict)
    raw_update_json: dict[str, Any]
    raw_message_json: dict[str, Any]
    ingested_at_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ParseResult(BaseModel):
    message: NormalizedMessage | None = None
    ignore_reason: str | None = None

    @property
    def is_ignored(self) -> bool:
        return self.message is None
