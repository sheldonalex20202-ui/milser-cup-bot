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
    def __init__(self, sender: TelegramSender, tickets: Any | None = None) -> None:
        self.sender = sender
        self.tickets = tickets

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
                message_id = (response.get("result") or {}).get("message_id")
                result["telegram_message_id"] = message_id
                if message_id is not None:
                    self._suppress_ticket_reply_match(recipient, int(message_id))
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

    def _suppress_ticket_reply_match(self, recipient: DirectBroadcastRecipient, message_id: int) -> None:
        if self.tickets is None:
            return
        suppress = getattr(self.tickets, "mark_direct_broadcast_suppressed", None)
        if suppress is None:
            return
        try:
            suppressed = bool(
                suppress(
                    recipient.chat_id,
                    recipient.direct_messages_topic_id,
                    message_id,
                )
            )
            if suppressed:
                logger.info(
                    "direct broadcast marked to skip ticket reply matching",
                    extra={
                        "_chat_id": recipient.chat_id,
                        "_direct_messages_topic_id": recipient.direct_messages_topic_id,
                        "_message_id": message_id,
                    },
                )
        except Exception as exc:
            logger.warning(
                "could not mark direct broadcast suppression",
                extra={
                    "_chat_id": recipient.chat_id,
                    "_direct_messages_topic_id": recipient.direct_messages_topic_id,
                    "_message_id": message_id,
                    "_error": str(exc),
                },
                exc_info=True,
            )
