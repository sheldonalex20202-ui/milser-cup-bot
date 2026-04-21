from typing import Any

from app.models.domain import ContentType


MEDIA_FIELDS: tuple[tuple[str, ContentType], ...] = (
    ("photo", ContentType.PHOTO),
    ("video", ContentType.VIDEO),
    ("animation", ContentType.ANIMATION),   # must be before document — GIFs have both fields
    ("document", ContentType.DOCUMENT),
    ("audio", ContentType.AUDIO),
    ("voice", ContentType.VOICE),
    ("video_note", ContentType.VIDEO_NOTE),
    ("sticker", ContentType.STICKER),
    ("contact", ContentType.CONTACT),
    ("location", ContentType.LOCATION),
    ("poll", ContentType.POLL),
)

CONTENT_LABELS: dict[ContentType, str] = {
    ContentType.PHOTO: "🖼 Фото",
    ContentType.VIDEO: "🎥 Видео",
    ContentType.VOICE: "🎤 Голосовое",
    ContentType.VIDEO_NOTE: "⭕ Кружочек",
    ContentType.STICKER: "🎭 Стикер",
    ContentType.DOCUMENT: "📎 Файл",
    ContentType.AUDIO: "🎵 Аудио",
    ContentType.ANIMATION: "🎬 GIF",
    ContentType.CONTACT: "📱 Контакт",
    ContentType.LOCATION: "📍 Геолокация",
    ContentType.POLL: "📊 Опрос",
}


def detect_content_type(message: dict[str, Any]) -> ContentType:
    for field_name, content_type in MEDIA_FIELDS:
        if field_name in message:
            return content_type
    if message.get("text"):
        return ContentType.TEXT
    return ContentType.OTHER


def has_user_content(message: dict[str, Any]) -> bool:
    if message.get("text") or message.get("caption"):
        return True
    return any(field_name in message for field_name, _ in MEDIA_FIELDS)


def extract_media_metadata(message: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}

    if "photo" in message:
        photos = message["photo"] or []
        metadata["photo"] = [
            {
                "file_id": item.get("file_id"),
                "file_unique_id": item.get("file_unique_id"),
                "width": item.get("width"),
                "height": item.get("height"),
                "file_size": item.get("file_size"),
            }
            for item in photos
        ]
    for field_name, _ in MEDIA_FIELDS:
        if field_name == "photo" or field_name not in message:
            continue
        value = message[field_name]
        if isinstance(value, dict):
            metadata[field_name] = {
                key: value.get(key)
                for key in (
                    "file_id",
                    "file_unique_id",
                    "file_name",
                    "mime_type",
                    "file_size",
                    "duration",
                    "width",
                    "height",
                    "emoji",
                    "latitude",
                    "longitude",
                    "phone_number",
                    "first_name",
                    "last_name",
                    "question",
                )
                if key in value
            }
        else:
            metadata[field_name] = value
    return metadata
