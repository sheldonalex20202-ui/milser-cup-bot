import json
from typing import Any

from app.models.domain import NormalizedMessage


MESSAGES_COLUMNS = [
    "ingested_at_utc",
    "source_type",
    "telegram_update_id",
    "telegram_chat_id",
    "telegram_message_id",
    "telegram_message_thread_id",
    "telegram_direct_messages_topic_id",
    "channel_chat_id",
    "discussion_group_chat_id",
    "channel_post_id",
    "user_id",
    "username",
    "first_name",
    "last_name",
    "message_date_utc",
    "content_type",
    "text",
    "caption",
    "media_json",
    "raw_message_json",
    "raw_update_json",
    "dedup_key",
    "schema_version",
]


def serialize_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def build_messages_row(message: NormalizedMessage) -> list[Any]:
    dedup_key = f"{message.telegram_update_id}:{message.telegram_chat_id}:{message.telegram_message_id}"
    return [
        message.ingested_at_utc.isoformat(),
        message.source_type.value,
        message.telegram_update_id,
        message.telegram_chat_id,
        message.telegram_message_id,
        message.telegram_message_thread_id,
        message.telegram_direct_messages_topic_id,
        message.channel_chat_id,
        message.discussion_group_chat_id,
        message.channel_post_id,
        message.user_id,
        message.username,
        message.first_name,
        message.last_name,
        message.message_date_utc.isoformat(),
        message.content_type.value,
        message.text,
        message.caption,
        serialize_json(message.media_json),
        serialize_json(message.raw_message_json),
        serialize_json(message.raw_update_json),
        dedup_key,
        1,
    ]
