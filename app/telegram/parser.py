from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings
from app.models.domain import NormalizedMessage, ParseResult, SourceType
from app.storage.sqlite import ThreadMappingRepository
from app.telegram.content import detect_content_type, extract_media_metadata, has_user_content


MESSAGE_UPDATE_KEYS = ("message",)


class TelegramUpdateParser:
    def __init__(self, settings: Settings, thread_mappings: ThreadMappingRepository) -> None:
        self.settings = settings
        self.thread_mappings = thread_mappings

    def parse(self, update: dict[str, Any]) -> ParseResult:
        update_id = update.get("update_id")
        message = self._extract_message(update)
        if update_id is None or message is None:
            return ParseResult(ignore_reason="not_message_update")

        self._record_thread_mapping_if_present(message)

        if not has_user_content(message):
            return ParseResult(ignore_reason="no_user_content")
        if self._is_edited_update(update):
            return ParseResult(ignore_reason="edited_messages_ignored")
        user = message.get("from")
        if not isinstance(user, dict):
            return ParseResult(ignore_reason="missing_user_sender")
        if user.get("is_bot"):
            return ParseResult(ignore_reason="bot_sender")
        if self.settings.telegram_bot_user_id and user.get("id") == self.settings.telegram_bot_user_id:
            return ParseResult(ignore_reason="self_bot_message")
        if user.get("id") in self.settings.telegram_support_admin_user_ids:
            return ParseResult(ignore_reason="support_admin_sender")
        if message.get("sender_chat"):
            return ParseResult(ignore_reason="sent_on_behalf_of_chat")

        source_type, channel_chat_id, channel_post_id = self._detect_source(message)
        if source_type is None:
            return ParseResult(ignore_reason="not_comment_or_direct")

        if source_type == SourceType.DIRECT and message.get("direct_messages_topic"):
            import logging as _log
            _log.getLogger(__name__).info(
                "community_dm_fields",
                extra={
                    "_thread_id": message.get("message_thread_id"),
                    "_dm_topic": message.get("direct_messages_topic"),
                    "_chat_id": (message.get("chat") or {}).get("id"),
                },
            )

        direct_topic = message.get("direct_messages_topic") or {}
        chat = message.get("chat") or {}
        normalized = NormalizedMessage(
            source_type=source_type,
            telegram_update_id=int(update_id),
            telegram_message_id=int(message["message_id"]),
            telegram_chat_id=int(chat["id"]),
            telegram_message_thread_id=message.get("message_thread_id"),
            telegram_direct_messages_topic_id=direct_topic.get("topic_id"),
            channel_chat_id=channel_chat_id,
            discussion_group_chat_id=(
                int(chat["id"]) if source_type == SourceType.COMMENT else None
            ),
            channel_post_id=channel_post_id,
            user_id=int(user["id"]),
            username=user.get("username"),
            first_name=user.get("first_name"),
            last_name=user.get("last_name"),
            message_date_utc=datetime.fromtimestamp(int(message["date"]), tz=timezone.utc),
            content_type=detect_content_type(message),
            text=message.get("text"),
            caption=message.get("caption"),
            media_json=extract_media_metadata(message),
            raw_update_json=update,
            raw_message_json=message,
        )
        return ParseResult(message=normalized)

    def _extract_message(self, update: dict[str, Any]) -> dict[str, Any] | None:
        for key in MESSAGE_UPDATE_KEYS:
            value = update.get(key)
            if isinstance(value, dict):
                return value
        return None

    def _is_edited_update(self, update: dict[str, Any]) -> bool:
        return "edited_message" in update or "edited_channel_post" in update

    def _detect_source(
        self, message: dict[str, Any]
    ) -> tuple[SourceType | None, int | None, int | None]:
        if self._is_direct_message(message):
            return SourceType.DIRECT, self.settings.telegram_channel_chat_id, None
        comment_meta = self._get_comment_channel_post(message)
        if comment_meta is not None:
            channel_chat_id, channel_post_id = comment_meta
            return SourceType.COMMENT, channel_chat_id, channel_post_id
        return None, None, None

    def _is_direct_message(self, message: dict[str, Any]) -> bool:
        if message.get("direct_messages_topic"):
            return True
        chat = message.get("chat") or {}
        return chat.get("type") == "private"

    def _get_comment_channel_post(self, message: dict[str, Any]) -> tuple[int | None, int | None] | None:
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if self.settings.telegram_discussion_group_chat_id is None:
            return None
        if chat_id != self.settings.telegram_discussion_group_chat_id:
            return None

        direct_reference = self._extract_channel_reference(message)
        if direct_reference is not None:
            return direct_reference

        thread_id = message.get("message_thread_id")
        if thread_id is not None:
            mapping = self.thread_mappings.get(int(chat_id), int(thread_id))
            if mapping:
                return mapping["channel_chat_id"], mapping["channel_post_id"]
            if self.settings.telegram_accept_unmapped_discussion_threads:
                return self.settings.telegram_channel_chat_id, None

        if self._looks_like_discussion_reply(message):
            return self.settings.telegram_channel_chat_id, None

        return None

    def _looks_like_discussion_reply(self, message: dict[str, Any]) -> bool:
        return bool(message.get("reply_to_message") or message.get("message_thread_id"))

    def _record_thread_mapping_if_present(self, message: dict[str, Any]) -> None:
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id != self.settings.telegram_discussion_group_chat_id:
            return

        reference = self._extract_channel_reference(message)
        if reference is None:
            return
        channel_chat_id, channel_post_id = reference
        thread_id = message.get("message_thread_id") or message.get("message_id")
        if thread_id is None:
            return
        self.thread_mappings.upsert(
            discussion_chat_id=int(chat_id),
            message_thread_id=int(thread_id),
            channel_chat_id=channel_chat_id,
            channel_post_id=channel_post_id,
            root_message_id=message.get("message_id"),
        )

    def _extract_channel_reference(self, message: dict[str, Any]) -> tuple[int | None, int | None] | None:
        for candidate in (
            message,
            message.get("reply_to_message") if isinstance(message.get("reply_to_message"), dict) else None,
        ):
            if not candidate:
                continue
            origin = candidate.get("forward_origin") or {}
            if origin.get("type") == "channel":
                chat = origin.get("chat") or {}
                return chat.get("id") or self.settings.telegram_channel_chat_id, origin.get("message_id")
            sender_chat = candidate.get("sender_chat") or {}
            if candidate.get("is_automatic_forward") and sender_chat.get("type") == "channel":
                return sender_chat.get("id") or self.settings.telegram_channel_chat_id, candidate.get("forward_from_message_id")

        external_reply = message.get("external_reply") or {}
        external_chat = external_reply.get("chat") or {}
        if external_chat.get("type") == "channel":
            return external_chat.get("id") or self.settings.telegram_channel_chat_id, external_reply.get("message_id")

        return None
