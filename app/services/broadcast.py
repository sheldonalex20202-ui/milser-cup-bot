import logging
import time
from dataclasses import dataclass
from typing import Any

from app.telegram.sender import TelegramSender

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DirectBroadcastRecipient:
    chat_id: int
    direct_messages_topic_id: int
    user_id: int | None = None
    username: str | None = None


class DirectBroadcastService:
    def __init__(self, sender: TelegramSender) -> None:
        self.sender = sender

    def send(
        self,
        text: str,
        recipients: list[DirectBroadcastRecipient],
        *,
        dry_run: bool = True,
        delay_seconds: float = 0.0,
    ) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        sent = 0
        failed = 0

        for index, recipient in enumerate(recipients):
            result: dict[str, Any] = {
                "chat_id": recipient.chat_id,
                "direct_messages_topic_id": recipient.direct_messages_topic_id,
                "user_id": recipient.user_id,
                "username": recipient.username,
                "status": "dry_run" if dry_run else "pending",
            }
            if dry_run:
                results.append(result)
                continue

            if delay_seconds > 0 and index > 0:
                time.sleep(delay_seconds)

            try:
                response = self.sender.send_message(
                    chat_id=recipient.chat_id,
                    direct_messages_topic_id=recipient.direct_messages_topic_id,
                    text=text,
                )
                result["status"] = "sent"
                result["telegram_message_id"] = (response.get("result") or {}).get("message_id")
                sent += 1
            except Exception as exc:
                result["status"] = "failed"
                result["error"] = str(exc)
                failed += 1
                logger.warning(
                    "direct broadcast failed",
                    extra={
                        "_chat_id": recipient.chat_id,
                        "_direct_messages_topic_id": recipient.direct_messages_topic_id,
                        "_error": str(exc),
                    },
                    exc_info=True,
                )
            results.append(result)

        return {
            "dry_run": dry_run,
            "requested": len(recipients),
            "sent": sent,
            "failed": failed,
            "results": results,
        }
