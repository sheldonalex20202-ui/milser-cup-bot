import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from app.models.domain import ContentType, NormalizedMessage, SourceType
from app.telegram.content import CONTENT_LABELS
from app.models.ticket import Ticket, TicketStatus
from app.sheets.client import GoogleSheetsClient
from app.sheets.ticket_rows import build_ticket_row
from app.storage.tickets import TicketRepository
from app.telegram.keyboard import close_keyboard, closed_keyboard, parse_callback_data, react_keyboard, reacted_keyboard
from app.telegram.sender import TelegramSender

logger = logging.getLogger(__name__)


class TicketService:
    def __init__(
        self,
        tickets: TicketRepository,
        sender: TelegramSender,
        sheets: GoogleSheetsClient,
        support_group_chat_id: int,
        bot_user_id: int | None = None,
        tz_offset: int = 3,
        day_start_hour: int = 9,
        night_start_hour: int = 21,
        community_username: str | None = None,
        support_topic_comments: int | None = None,
        support_topic_direct: int | None = None,
    ) -> None:
        self.tickets = tickets
        self.sender = sender
        self.sheets = sheets
        self.support_group_chat_id = support_group_chat_id
        self.bot_user_id = bot_user_id
        self.tz_offset = tz_offset
        self.day_start_hour = day_start_hour
        self.night_start_hour = night_start_hour
        self.community_username = community_username
        self.support_topic_comments = support_topic_comments
        self.support_topic_direct = support_topic_direct

    # ------------------------------------------------------------------
    # Public API called from routes
    # ------------------------------------------------------------------

    def create_ticket(self, message: NormalizedMessage) -> Ticket:
        text = message.text or message.caption or ""

        # If the user already has an open ticket, append to it instead of creating new
        existing = self.tickets.get_open_for_user(message.user_id, message.telegram_chat_id)
        if existing:
            self._append_to_ticket(existing, message)
            logger.info(
                "message appended to existing ticket",
                extra={"_ticket_id": existing.id, "_ticket_code": existing.ticket_code},
            )
            return existing

        ticket_code = self._generate_ticket_code()
        ticket = self.tickets.create(
            ticket_code=ticket_code,
            source_type=message.source_type.value,
            user_id=message.user_id,
            username=message.username,
            first_name=message.first_name,
            user_chat_id=message.telegram_chat_id,
            user_message_id=message.telegram_message_id,
            user_message_thread_id=message.telegram_message_thread_id or message.telegram_direct_messages_topic_id,
            user_message_text=text[:4000] if text else None,
        )

        support_msg = self._send_ticket_to_support(ticket, message)
        support_msg_id = support_msg.get("result", {}).get("message_id")
        if support_msg_id:
            self.tickets.set_support_message(ticket.id, support_msg_id)
            self.tickets.track_message(ticket.id, "support", support_msg_id)
            ticket.support_group_message_id = support_msg_id

        logger.info("ticket created", extra={"_ticket_code": ticket.ticket_code, "_ticket_id": ticket.id})
        return ticket

    def is_community_dm_reply(self, update: dict[str, Any]) -> bool:
        """True when an admin writes in a community DM topic on behalf of the community."""
        message = update.get("message")
        if not isinstance(message, dict):
            return False
        if not message.get("sender_chat"):
            return False
        if not message.get("direct_messages_topic"):
            return False
        return True

    def handle_community_dm_reply(self, message: dict[str, Any]) -> None:
        dm_topic = message.get("direct_messages_topic") or {}
        topic_id = dm_topic.get("topic_id")
        chat_id = (message.get("chat") or {}).get("id")
        if not topic_id or not chat_id:
            return

        ticket = self.tickets.get_open_direct_by_dm_topic(chat_id, topic_id)
        if not ticket:
            logger.info("community dm reply — no open ticket found", extra={"_chat_id": chat_id, "_topic": topic_id})
            return
        if ticket.status == TicketStatus.CLOSED:
            return

        answer_text = message.get("text") or message.get("caption") or ""
        from app.telegram.content import detect_content_type
        content_type = detect_content_type(message)
        media_label = CONTENT_LABELS.get(content_type, "")
        preview_text = answer_text or media_label

        answer_msg = self._send_answer_delivered(ticket, preview_text)
        answer_msg_id = answer_msg.get("result", {}).get("message_id")
        if answer_msg_id:
            self.tickets.track_message(ticket.id, "answer_delivered", answer_msg_id)

        if content_type not in (ContentType.TEXT, ContentType.OTHER) and chat_id:
            try:
                if content_type == ContentType.STICKER:
                    file_id = (message.get("sticker") or {}).get("file_id")
                    if file_id:
                        self.sender.send_sticker(
                            chat_id=self.support_group_chat_id,
                            sticker=file_id,
                            reply_to_message_id=answer_msg_id,
                        )
                else:
                    self.sender.copy_message(
                        chat_id=self.support_group_chat_id,
                        from_chat_id=chat_id,
                        message_id=message.get("message_id"),
                        reply_to_message_id=answer_msg_id,
                    )
            except Exception as exc:
                logger.warning("could not copy admin media to support", extra={"_error": str(exc)})

        self.tickets.mark_answered(ticket.id, answer_msg_id or 0)
        logger.info("community dm ticket answered", extra={"_ticket_id": ticket.id, "_ticket_code": ticket.ticket_code})

    def is_admin_reply(self, update: dict[str, Any]) -> bool:
        """True when the update is an admin reply to a ticket message in the support group."""
        message = update.get("message")
        if not isinstance(message, dict):
            return False
        chat_id = (message.get("chat") or {}).get("id")
        if chat_id != self.support_group_chat_id:
            return False
        reply_to = message.get("reply_to_message")
        if not isinstance(reply_to, dict):
            return False
        # Sender must not be the bot itself
        sender_id = (message.get("from") or {}).get("id")
        if self.bot_user_id and sender_id == self.bot_user_id:
            return False
        reply_msg_id = reply_to.get("message_id")
        if not reply_msg_id:
            return False
        return self.tickets.get_ticket_by_any_message(reply_msg_id) is not None

    def handle_admin_reply(self, message: dict[str, Any]) -> None:
        reply_to = message.get("reply_to_message", {})
        reply_msg_id = reply_to.get("message_id")
        ticket = self.tickets.get_ticket_by_any_message(reply_msg_id)
        if not ticket:
            return
        if ticket.status == TicketStatus.CLOSED:
            logger.info("admin reply ignored — ticket already closed", extra={"_ticket_id": ticket.id})
            return

        answer_text = message.get("text") or message.get("caption") or ""

        # Deliver reply to user
        self._send_reply_to_user(ticket, answer_text)

        # Post "answer delivered" + close button in support group
        answer_msg = self._send_answer_delivered(ticket, answer_text)
        answer_msg_id = answer_msg.get("result", {}).get("message_id")
        if answer_msg_id:
            self.tickets.track_message(ticket.id, "answer_delivered", answer_msg_id)

        self.tickets.mark_answered(ticket.id, answer_msg_id or 0)
        logger.info("ticket answered", extra={"_ticket_id": ticket.id, "_ticket_code": ticket.ticket_code})

    def handle_callback(self, callback_query: dict[str, Any]) -> None:
        query_id: str = callback_query.get("id", "")
        data: str = callback_query.get("data", "")
        caller = callback_query.get("from") or {}
        caller_id: int = caller.get("id", 0)

        parsed = parse_callback_data(data)
        if not parsed:
            self._safe_answer_callback(query_id)
            return

        action, ticket_id = parsed

        if action == "noop":
            self._safe_answer_callback(query_id)
            return

        ticket = self.tickets.get_by_id(ticket_id)
        if not ticket:
            self._safe_answer_callback(query_id, "Тикет не найден")
            return

        if action == "react":
            self._handle_react(ticket, query_id, caller_id)
        elif action == "close":
            self._handle_close(ticket, query_id, caller_id)
        elif action == "delete":
            self._handle_delete(ticket, query_id)

    def ensure_sheets_ready(self) -> None:
        self.sheets.ensure_tickets_header()

    def sync_closed_tickets(self) -> int:
        synced = 0
        for ticket in self.tickets.get_unsync_closed():
            try:
                row = build_ticket_row(ticket, self.tz_offset)
                row_number = self.sheets.append_ticket_row(row)
                self.tickets.mark_sheets_synced(ticket.id)
                if row_number:
                    self.sheets.color_source_cells(row_number, ticket.source_type)
                synced += 1
                logger.info("ticket synced to sheets", extra={"_ticket_id": ticket.id})
            except Exception as exc:
                logger.error("ticket sheets sync failed", extra={"_ticket_id": ticket.id, "_error": str(exc)})
        return synced

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _handle_react(self, ticket: Ticket, query_id: str, caller_id: int) -> None:
        if ticket.status != TicketStatus.NEW:
            self._safe_answer_callback(query_id, "Уже отреагировали на этот тикет")
            return

        # Answer immediately so the button spinner stops
        self._safe_answer_callback(query_id, "✅ Реакция зафиксирована")

        self.tickets.mark_reacted(ticket.id, caller_id)
        ticket = self.tickets.get_by_id(ticket.id)  # type: ignore[assignment]

        # Replace button with "Отреагировано" status label
        if ticket.support_group_message_id:
            try:
                dm_url = self._build_dm_url(ticket) if ticket.source_type == SourceType.DIRECT else None
                self.sender.edit_message_reply_markup(
                    self.support_group_chat_id, ticket.support_group_message_id, reacted_keyboard(dm_url)
                )
            except Exception as exc:
                logger.warning("could not update react button", extra={"_error": str(exc)})

        # Notify user
        notification = (
            f"✅ <b>Ваш запрос принят!</b>\n\n"
            f"Тикет: <b>{ticket.ticket_code}</b>\n"
            f"Специалист уже изучает ваше сообщение. Ожидайте ответ."
        )
        self._safe_send_to_user(ticket, notification)
        logger.info("ticket reacted", extra={"_ticket_id": ticket.id, "_by": caller_id})

    def _handle_close(self, ticket: Ticket, query_id: str, caller_id: int) -> None:
        if ticket.status == TicketStatus.CLOSED:
            self._safe_answer_callback(query_id, "Тикет уже закрыт")
            return

        # Answer immediately so the button spinner stops
        self._safe_answer_callback(query_id, "🔒 Тикет закрыт")

        self.tickets.mark_closed(ticket.id, caller_id)
        ticket = self.tickets.get_by_id(ticket.id)  # type: ignore[assignment]

        # Replace ALL "Закрыть тикет" buttons across every "answer_delivered" message
        for mid in self.tickets.get_answer_delivered_ids(ticket.id):
            try:
                self.sender.edit_message_reply_markup(self.support_group_chat_id, mid, closed_keyboard(ticket.id))
            except Exception as exc:
                logger.warning("could not update close button", extra={"_msg_id": mid, "_error": str(exc)})

        # Sync to Google Sheets immediately
        row_number: int | None = None
        try:
            row = build_ticket_row(ticket, self.tz_offset)
            row_number = self.sheets.append_ticket_row(row)
            self.tickets.mark_sheets_synced(ticket.id)
            logger.info("ticket appended to sheets", extra={"_ticket_id": ticket.id, "_row": row_number})
        except Exception as exc:
            logger.error("ticket sheets append failed", extra={"_ticket_id": ticket.id, "_error": str(exc)})

        if row_number:
            try:
                self.sheets.color_source_cells(row_number, ticket.source_type)
            except Exception as exc:
                logger.error("ticket color cells failed", extra={"_ticket_id": ticket.id, "_row": row_number, "_error": str(exc)})

        logger.info("ticket closed", extra={"_ticket_id": ticket.id, "_by": caller_id})

    def _handle_delete(self, ticket: Ticket, query_id: str) -> None:
        self._safe_answer_callback(query_id, "🗑 Сообщения удалены")

        message_ids: set[int] = set()
        if ticket.support_group_message_id:
            message_ids.add(ticket.support_group_message_id)
        for mid in self.tickets.get_all_support_message_ids(ticket.id):
            message_ids.add(mid)

        for mid in message_ids:
            try:
                self.sender.delete_message(self.support_group_chat_id, mid)
            except Exception as exc:
                logger.warning("could not delete message", extra={"_msg_id": mid, "_error": str(exc)})

        logger.info("ticket messages deleted", extra={"_ticket_id": ticket.id, "_count": len(message_ids)})

    def _append_to_ticket(self, ticket: Ticket, message: NormalizedMessage) -> None:
        text = message.text or message.caption or ""
        content_type = message.content_type
        media_label = CONTENT_LABELS.get(content_type, "")
        preview = ""
        if text:
            preview = f"\n\n<blockquote>{_escape(text)}</blockquote>"
        elif media_label:
            preview = f"\n{media_label}"
        msg = (
            f"📨 <b>Новое сообщение по тикету {ticket.ticket_code}</b>\n"
            f"👤 {_escape(ticket.display_name)}"
            f"{preview}"
        )
        try:
            result = self.sender.send_message(
                chat_id=self.support_group_chat_id,
                text=msg,
                reply_to_message_id=ticket.support_group_message_id,
                message_thread_id=self._support_thread(ticket.source_type),
            )
            msg_id = result.get("result", {}).get("message_id")
            if msg_id:
                self.tickets.track_message(ticket.id, "continuation", msg_id)
            if content_type not in (ContentType.TEXT, ContentType.OTHER):
                self._copy_media_to_support(message, msg_id)
        except Exception as exc:
            logger.warning("could not forward continuation message", extra={"_ticket_id": ticket.id, "_error": str(exc)})

    def _send_ticket_to_support(self, ticket: Ticket, source_message: NormalizedMessage | None = None) -> dict[str, Any]:
        source_label = "💬 Комментарий" if ticket.source_type == SourceType.COMMENT else "📩 Директ"
        created_dt = _fmt_dt(ticket.created_at_utc)

        content_type = source_message.content_type if source_message else ContentType.TEXT
        media_label = CONTENT_LABELS.get(content_type, "")
        text_preview = ""
        if ticket.user_message_text:
            text_preview = f"\n\n<blockquote>{_escape(ticket.user_message_text)}</blockquote>"
        elif media_label:
            text_preview = f"\n{media_label}"

        text = (
            f"🎫 <b>Тикет {ticket.ticket_code}</b>\n"
            f"📅 {created_dt}\n"
            f"👤 {_escape(ticket.display_name)}\n"
            f"📍 {source_label}"
            f"{text_preview}"
        )
        dm_url = self._build_dm_url(ticket) if ticket.source_type == SourceType.DIRECT else None
        result = self.sender.send_message(
            chat_id=self.support_group_chat_id,
            text=text,
            reply_markup=react_keyboard(ticket.id, dm_url),
            message_thread_id=self._support_thread(ticket.source_type),
        )
        if source_message and content_type not in (ContentType.TEXT, ContentType.OTHER):
            self._copy_media_to_support(source_message, result.get("result", {}).get("message_id"))
        return result

    def _send_reply_to_user(self, ticket: Ticket, answer_text: str) -> None:
        text = f"💬 <b>Ответ службы поддержки:</b>\n\n{_escape(answer_text)}"
        self._safe_send_to_user(ticket, text)

    def _send_answer_delivered(self, ticket: Ticket, answer_text: str) -> dict[str, Any]:
        preview = _escape(answer_text[:300]) + ("…" if len(answer_text) > 300 else "")
        text = (
            f"✅ <b>Ответ доставлен</b>\n"
            f"📋 Тикет: <b>{ticket.ticket_code}</b>\n\n"
            f"💬 <i>{preview}</i>"
        )
        return self.sender.send_message(
            chat_id=self.support_group_chat_id,
            text=text,
            reply_markup=close_keyboard(ticket.id),
            message_thread_id=self._support_thread(ticket.source_type),
        )

    def _support_thread(self, source_type: str) -> int | None:
        if source_type == SourceType.COMMENT:
            return self.support_topic_comments
        return self.support_topic_direct

    def _copy_media_to_support(self, message: NormalizedMessage, reply_to_message_id: int | None) -> None:
        try:
            if message.content_type == ContentType.STICKER:
                file_id = (message.media_json.get("sticker") or {}).get("file_id")
                if file_id:
                    self.sender.send_sticker(
                        chat_id=self.support_group_chat_id,
                        sticker=file_id,
                        reply_to_message_id=reply_to_message_id,
                    )
                    return
            self.sender.copy_message(
                chat_id=self.support_group_chat_id,
                from_chat_id=message.telegram_chat_id,
                message_id=message.telegram_message_id,
                reply_to_message_id=reply_to_message_id,
            )
        except Exception as exc:
            logger.warning("could not copy media to support", extra={"_error": str(exc)})

    def _build_dm_url(self, ticket: Ticket) -> str | None:
        if not self.community_username:
            return None
        username = self.community_username.lstrip("@")
        return f"https://t.me/{username}?direct"

    def _safe_send_to_user(self, ticket: Ticket, text: str) -> None:
        try:
            kwargs: dict[str, Any] = {}
            if ticket.source_type == SourceType.COMMENT:
                kwargs["reply_to_message_id"] = ticket.user_message_id
                if ticket.user_message_thread_id:
                    kwargs["message_thread_id"] = ticket.user_message_thread_id
            elif ticket.user_message_thread_id:
                kwargs["message_thread_id"] = ticket.user_message_thread_id
            self.sender.send_message(chat_id=ticket.user_chat_id, text=text, **kwargs)
        except Exception as exc:
            logger.warning(
                "could not send message to user",
                extra={
                    "_ticket_id": ticket.id,
                    "_user_chat_id": ticket.user_chat_id,
                    "_thread_id": ticket.user_message_thread_id,
                    "_source": ticket.source_type,
                    "_error": str(exc),
                },
                exc_info=True,
            )

    def _safe_answer_callback(self, query_id: str, text: str | None = None) -> None:
        try:
            self.sender.answer_callback_query(query_id, text)
        except Exception as exc:
            logger.warning("could not answer callback", extra={"_error": str(exc)})

    def _generate_ticket_code(self) -> str:
        tz = timezone(timedelta(hours=self.tz_offset))
        now_local = datetime.now(tz)
        hour = now_local.hour
        shift = "D" if self.day_start_hour <= hour < self.night_start_hour else "N"
        ddmm = now_local.strftime("%d%m")

        local_midnight = datetime.combine(now_local.date(), time(0, 0), tzinfo=tz)
        utc_start = local_midnight.astimezone(timezone.utc).isoformat()
        utc_end = (local_midnight + timedelta(days=1)).astimezone(timezone.utc).isoformat()

        seq = self.tickets.count_today_tickets(utc_start, utc_end) + 1
        return f"{shift}{ddmm}-{seq:02d}"


def _escape(text: str | None) -> str:
    if not text:
        return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt_dt(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%d.%m.%Y %H:%M UTC")
    except Exception:
        return iso
