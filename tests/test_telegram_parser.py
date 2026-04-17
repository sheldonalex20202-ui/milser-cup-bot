from pathlib import Path
from uuid import uuid4

from app.core.config import Settings
from app.models.domain import ContentType, SourceType
from app.storage.sqlite import SQLiteDatabase, ThreadMappingRepository
from app.telegram.parser import TelegramUpdateParser


def runtime_dir() -> Path:
    path = Path("test-data") / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


def make_settings(base_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        telegram_bot_token="1234567890:test-token",
        telegram_webhook_secret_token="x" * 32,
        telegram_bot_user_id=9000,
        telegram_channel_chat_id=-100111,
        telegram_discussion_group_chat_id=-100222,
        telegram_support_admin_user_ids=[7001],
        sqlite_path=base_path / "app.db",
        google_credentials_path=base_path / "sa.json",
        google_spreadsheet_id="spreadsheet-id-123",
    )


def make_parser() -> TelegramUpdateParser:
    settings = make_settings(runtime_dir())
    db = SQLiteDatabase(settings.sqlite_path)
    db.initialize()
    return TelegramUpdateParser(settings, ThreadMappingRepository(db))


def user_message(**overrides):
    sender = overrides.pop(
        "from_",
        {
            "id": 500,
            "is_bot": False,
            "username": "alice",
            "first_name": "Alice",
        },
    )
    message = {
        "message_id": 10,
        "date": 1_700_000_000,
        "chat": {"id": 123, "type": "private"},
        "from": sender,
        "text": "hello",
    }
    message.update(overrides)
    return {"update_id": 1000, "message": message}


def test_direct_message_from_private_chat():
    parser = make_parser()

    result = parser.parse(user_message())

    assert not result.is_ignored
    assert result.message is not None
    assert result.message.source_type == SourceType.DIRECT
    assert result.message.text == "hello"


def test_direct_message_topic_id_is_saved():
    parser = make_parser()

    result = parser.parse(
        user_message(
            chat={"id": -100333, "type": "supergroup"},
            direct_messages_topic={"topic_id": 1234567890123},
        )
    )

    assert result.message is not None
    assert result.message.source_type == SourceType.DIRECT
    assert result.message.telegram_direct_messages_topic_id == 1234567890123


def test_discussion_group_message_without_mapping_is_ignored():
    parser = make_parser()

    result = parser.parse(
        user_message(
            chat={"id": -100222, "type": "supergroup"},
            message_thread_id=55,
        )
    )

    assert result.is_ignored
    assert result.ignore_reason == "not_comment_or_direct"


def test_comment_is_detected_from_stored_thread_mapping():
    parser = make_parser()

    root_update = user_message(
        message_id=55,
        chat={"id": -100222, "type": "supergroup"},
        from_ignored="unused",
        sender_chat={"id": -100111, "type": "channel"},
        is_automatic_forward=True,
        forward_origin={
            "type": "channel",
            "chat": {"id": -100111, "type": "channel"},
            "message_id": 777,
        },
    )
    root_update["message"].pop("from")
    parser.parse(root_update)

    result = parser.parse(
        user_message(
            message_id=56,
            chat={"id": -100222, "type": "supergroup"},
            message_thread_id=55,
            text="comment",
        )
    )

    assert result.message is not None
    assert result.message.source_type == SourceType.COMMENT
    assert result.message.channel_chat_id == -100111
    assert result.message.channel_post_id == 777
    assert result.message.discussion_group_chat_id == -100222


def test_admin_and_sender_chat_messages_are_ignored():
    parser = make_parser()

    admin_result = parser.parse(
        user_message(
            from_={"id": 7001, "is_bot": False, "first_name": "Admin"},
        )
    )
    sender_chat_result = parser.parse(user_message(sender_chat={"id": -100222, "type": "supergroup"}))

    assert admin_result.is_ignored
    assert sender_chat_result.is_ignored


def test_photo_caption_message_is_normalized():
    parser = make_parser()

    update = user_message(
        text=None,
        caption="look",
        photo=[
            {"file_id": "small", "file_unique_id": "u1", "width": 90, "height": 90},
            {"file_id": "large", "file_unique_id": "u2", "width": 1280, "height": 720},
        ],
    )
    update["message"].pop("text")

    result = parser.parse(update)

    assert result.message is not None
    assert result.message.content_type == ContentType.PHOTO
    assert result.message.caption == "look"
    assert result.message.media_json["photo"][1]["file_id"] == "large"
