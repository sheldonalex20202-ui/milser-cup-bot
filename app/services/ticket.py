import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from app.models.domain import ContentType, NormalizedMessage, SourceType
from app.telegram.content import CONTENT_LABELS
from app.models.ticket import Ticket, TicketStatus
from app.sheets.client import GoogleSheetsClient
from app.sheets.ticket_rows import build_initial_ticket_row, build_ticket_row
from app.storage.tickets import TicketRepository
from app.telegram.keyboard import close_keyboard, closed_keyboard, deleted_keyboard, parse_callback_data, react_keyboard, reacted_keyboard
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
        support_topic_warnings: int | None = None,
        support_admin_user_ids: list[int] | None = None,
        alert_threshold_seconds: int = 60,
        alert_repeat_seconds: int = 1800,
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
        self.support_topic_warnings = support_topic_warnings
        self.support_admin_user_ids = set(support_admin_user_ids or [])
        self.alert_threshold_seconds = alert_threshold_seconds
        self.alert_repeat_seconds = alert_repeat_seconds

    # ------------------------------------------------------------------
    # Public API called from routes
    # ------------------------------------------------------------------

    def create_ticket(self, message: NormalizedMessage) -> Ticket:
        text = message.text or message.caption or ""

        existing = self.tickets.get_open_for_user(message.user_id, message.telegram_chat_id)
        has_real_ticket = existing and existing.status not in (TicketStatus.PREVIEW, TicketStatus.CLOSED)

        # Stickers and GIFs from comments are ignored until a real ticket exists
        if (message.source_type == SourceType.COMMENT
                and message.content_type in (ContentType.STICKER, ContentType.ANIMATION)):
            if not has_real_ticket:
                logger.info("comment sticker/gif ignored — no active ticket",
                            extra={"_user_id": message.user_id})
                return None

        # Append to an existing open ticket — but NOT to a preview (preview = ticket not yet created)
        if has_real_ticket:
            self._append_to_ticket(existing, message)  # type: ignore[arg-type]
            logger.info(
                "message appended to existing ticket",
                extra={"_ticket_id": existing.id, "_ticket_code": existing.ticket_code},  # type: ignore[union-attr]
            )
            return existing

        if message.source_type == SourceType.COMMENT:
            # Create a preview: no ticket code, no sheets row — ticket is "born" on react
            ticket = self.tickets.create(
                ticket_code="",
                status="preview",
                source_type=message.source_type.value,
                user_id=message.user_id,
                username=message.username,
                first_name=message.first_name,
                user_chat_id=message.telegram_chat_id,
                user_message_id=message.telegram_message_id,
                user_message_thread_id=message.telegram_message_thread_id,
                user_message_text=text[:4000] if text else None,
            )
            preview_msg = self._send_preview_to_support(ticket, message)
            preview_msg_id = preview_msg.get("result", {}).get("message_id")
            if preview_msg_id:
                self.tickets.set_support_message(ticket.id, preview_msg_id)
                self.tickets.track_message(ticket.id, "support", preview_msg_id)
                ticket.support_group_message_id = preview_msg_id
            logger.info("comment preview created", extra={"_ticket_id": ticket.id})
        else:
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
            self._sheets_append_initial(ticket)
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
        ticket = self.tickets.get_by_id(ticket.id)  # type: ignore[assignment]
        if not self._is_supabase_backend():
            self._sheets_update_cell(ticket, "H", ticket.answered_at_utc)
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

    def is_ticket_list_command(self, update: dict[str, Any]) -> bool:
        message = update.get("message")
        if not isinstance(message, dict):
            return False
        chat_id = (message.get("chat") or {}).get("id")
        thread_id = message.get("message_thread_id")
        command = (message.get("text") or message.get("caption") or "").strip().split(maxsplit=1)[0].lower()
        command = command.split("@", 1)[0]
        if command not in ("/tikets", "/tickets"):
            return False
        if chat_id == self.support_group_chat_id:
            return True
        return self.support_topic_warnings is not None and thread_id == self.support_topic_warnings

    def handle_ticket_list_command(self, message: dict[str, Any]) -> None:
        chat_id = (message.get("chat") or {}).get("id") or self.support_group_chat_id
        thread_id = message.get("message_thread_id")
        tickets = self.tickets.get_active_tickets(limit=100)
        if not tickets:
            text = "Активных тикетов нет."
        else:
            lines = ["<b>Активные тикеты</b>"]
            for ticket in tickets:
                lines.append(f"{_escape(_ticket_label(ticket))} — {_status_label(ticket.status)}")
            text = "\n".join(lines)
        try:
            self.sender.send_message(
                chat_id=chat_id,
                text=text,
                reply_to_message_id=message.get("message_id"),
                message_thread_id=thread_id,
            )
            logger.info(
                "ticket list command answered",
                extra={"_chat_id": chat_id, "_message_thread_id": thread_id, "_ticket_count": len(tickets)},
            )
        except Exception as exc:
            logger.warning(
                "ticket list reply failed, retrying without reply",
                extra={"_chat_id": chat_id, "_message_thread_id": thread_id, "_error": str(exc)},
            )
            self.sender.send_message(
                chat_id=chat_id,
                text=text,
                message_thread_id=thread_id,
            )

    def handle_admin_reply(self, message: dict[str, Any]) -> None:
        reply_to = message.get("reply_to_message", {})
        reply_msg_id = reply_to.get("message_id")
        ticket = self.tickets.get_ticket_by_any_message(reply_msg_id)
        if not ticket:
            return
        if ticket.status == TicketStatus.CLOSED:
            logger.info("admin reply ignored — ticket already closed", extra={"_ticket_id": ticket.id})
            return

        # For DIRECT tickets, admin must use the "Ответить в директ" button, not a plain reply
        if ticket.source_type == SourceType.DIRECT:
            try:
                admin_msg_id = message.get("message_id")
                self.sender.send_message(
                    chat_id=self.support_group_chat_id,
                    text=(
                        "⚠️ <b>Ответ не доставлен</b>\n\n"
                        "Для тикетов из директа отвечайте через кнопку "
                        "<b>«💬 Ответить в директ»</b> — напишите ответ напрямую пользователю в сообщества. "
                        "Прочитайте <a href=\"https://docs.google.com/document/d/1aJz89SAOxtm8B55P5k5BPLdZn8oS73PLMfgDWp47bIw/edit?tab=t.0#heading=h.pbo9y4it6hzv\">инструкцию</a> для ознакомления."
                    ),
                    reply_to_message_id=admin_msg_id,
                    message_thread_id=self._support_thread(ticket.source_type),
                )
            except Exception as exc:
                logger.warning("could not send direct reply warning", extra={"_error": str(exc)})
            return

        answer_text = message.get("text") or message.get("caption") or ""
        from app.telegram.content import detect_content_type
        content_type = detect_content_type(message)

        # Deliver reply to user
        if content_type in (ContentType.TEXT, ContentType.OTHER):
            user_reply_msg_id = self._send_reply_to_user(ticket, answer_text)
        else:
            user_reply_msg_id = self._copy_media_to_user(ticket, message)
        if user_reply_msg_id and ticket.source_type == SourceType.COMMENT:
            self.tickets.track_message(ticket.id, "user_reply", user_reply_msg_id)

        # Post "answer delivered" + close button in support group
        preview_text = answer_text or CONTENT_LABELS.get(content_type, "")
        answer_msg = self._send_answer_delivered(ticket, preview_text)
        answer_msg_id = answer_msg.get("result", {}).get("message_id")
        if answer_msg_id:
            self.tickets.track_message(ticket.id, "answer_delivered", answer_msg_id)

        self.tickets.mark_answered(ticket.id, answer_msg_id or 0)
        ticket = self.tickets.get_by_id(ticket.id)  # type: ignore[assignment]
        if not self._is_supabase_backend():
            self._sheets_update_cell(ticket, "H", ticket.answered_at_utc)
        logger.info("ticket answered", extra={"_ticket_id": ticket.id, "_ticket_code": ticket.ticket_code})

    def build_callback_ack(self, callback_query: dict[str, Any]) -> dict[str, Any]:
        query_id = callback_query.get("id", "")
        data = callback_query.get("data", "")
        parsed = parse_callback_data(data)
        if not parsed:
            return {"method": "answerCallbackQuery", "callback_query_id": query_id}
        action, _ticket_id = parsed
        text = {
            "react": "Реакция фиксируется...",
            "close": "Закрываю тикет...",
            "delete": "Удаляю сообщение...",
        }.get(action)
        payload: dict[str, Any] = {"method": "answerCallbackQuery", "callback_query_id": query_id}
        if text:
            payload["text"] = text
        return payload

    def acknowledge_callback(self, callback_query: dict[str, Any]) -> None:
        ack = self.build_callback_ack(callback_query)
        self._safe_answer_callback(ack["callback_query_id"], ack.get("text"))

    def handle_callback(self, callback_query: dict[str, Any], acknowledge: bool = True) -> None:
        query_id: str = callback_query.get("id", "")
        data: str = callback_query.get("data", "")
        caller = callback_query.get("from") or {}
        caller_id: int = caller.get("id", 0)

        parsed = parse_callback_data(data)
        if not parsed:
            if acknowledge:
                self._safe_answer_callback(query_id)
            return

        action, ticket_id = parsed

        if action == "noop":
            if acknowledge:
                self._safe_answer_callback(query_id)
            return

        ticket = self.tickets.get_by_id(ticket_id)
        if not ticket:
            if acknowledge:
                self._safe_answer_callback(query_id, "Тикет не найден")
            return

        if action == "react":
            self._handle_react(ticket, query_id, caller_id, acknowledge=acknowledge)
        elif action == "close":
            self._handle_close(ticket, query_id, caller_id, acknowledge=acknowledge)
        elif action == "delete":
            msg_id = (callback_query.get("message") or {}).get("message_id")
            self._handle_delete(ticket, query_id, msg_id, acknowledge=acknowledge)

    def ensure_sheets_ready(self) -> None:
        self.sheets.ensure_tickets_header()

    def sync_closed_tickets(self) -> int:
        synced = self.sync_missing_ticket_rows()
        for ticket in self.tickets.get_unsync_closed():
            if not ticket.ticket_code:
                self.tickets.mark_sheets_synced(ticket.id)
                self._purge_closed_synced()
                continue
            try:
                if ticket.sheets_row_number:
                    # Row already exists — fill deferred status timestamps before purge.
                    self._sheets_update_cell(ticket, "G", ticket.reacted_at_utc)
                    self._sheets_update_cell(ticket, "H", ticket.answered_at_utc)
                    self._sheets_update_cell(ticket, "I", ticket.closed_at_utc)
                else:
                    # Fallback for tickets created before incremental writes
                    row = build_ticket_row(ticket, self.tz_offset)
                    row_number = self.sheets.append_ticket_row(row)
                    if row_number:
                        self.sheets.color_source_cells(row_number, ticket.source_type)
                self.tickets.mark_sheets_synced(ticket.id)
                synced += 1
                logger.info("ticket synced to sheets", extra={"_ticket_id": ticket.id})
                self._purge_closed_synced()
            except Exception as exc:
                logger.error("ticket sheets sync failed", extra={"_ticket_id": ticket.id, "_error": str(exc)})
        self._purge_closed_synced()
        return synced

    def sync_missing_ticket_rows(self) -> int:
        synced = 0
        for ticket in self.tickets.get_without_sheets_row():
            try:
                self._sheets_append_initial(ticket)
                synced += 1
            except Exception as exc:
                logger.error("ticket initial sheets backfill failed", extra={"_ticket_id": ticket.id, "_error": str(exc)})
        return synced

    def check_stale_tickets(self) -> int:
        if not self.support_topic_warnings:
            return 0
        sent = 0
        for ticket, alert_type in self.tickets.get_stale_tickets(
            self.alert_threshold_seconds,
            self.alert_repeat_seconds,
        ):
            try:
                alert_text = self._build_alert_text(ticket, alert_type)
                result = self._send_warning(ticket, alert_text)
                msg_id = (result.get("result") or {}).get("message_id")
                if self.tickets.record_ticket_alert(ticket.id, alert_type, msg_id):
                    sent += 1
                    logger.info(
                        "ticket alert sent",
                        extra={"_ticket_id": ticket.id, "_alert_type": alert_type, "_message_id": msg_id},
                    )
            except Exception as exc:
                logger.warning(
                    "ticket alert failed",
                    extra={"_ticket_id": ticket.id, "_alert_type": alert_type, "_error": str(exc)},
                    exc_info=True,
                )
        return sent

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_alert_text(self, ticket: Ticket, alert_type: str) -> str:
        label = _ticket_label(ticket)
        status_text = {
            "primary_reaction": "ожидает первичной реакции",
            "secondary_reaction": "ожидает вторичной реакции",
            "close": "ожидает закрытия",
        }.get(alert_type, "требует внимания")
        return (
            f"⚠️ <b>Предупреждение</b>\n\n"
            f"Тикет <b>{_escape(label)}</b> {status_text}."
        )

    def _send_warning(self, ticket: Ticket, text: str) -> dict[str, Any]:
        try:
            return self.sender.send_message(
                chat_id=self.support_group_chat_id,
                text=text,
                reply_to_message_id=ticket.support_group_message_id,
                message_thread_id=self.support_topic_warnings,
            )
        except Exception:
            # Telegram may reject cross-topic replies. Keep the warning in the warnings topic.
            return self.sender.send_message(
                chat_id=self.support_group_chat_id,
                text=text,
                message_thread_id=self.support_topic_warnings,
            )

    def _handle_react(self, ticket: Ticket, query_id: str, caller_id: int, acknowledge: bool = True) -> None:
        if ticket.status not in (TicketStatus.NEW, TicketStatus.PREVIEW):
            if acknowledge:
                self._safe_answer_callback(query_id, "Уже отреагировали на этот тикет")
            return

        # Answer immediately so the button spinner stops
        if acknowledge:
            self._safe_answer_callback(query_id, "✅ Реакция зафиксирована")

        was_preview = ticket.status == TicketStatus.PREVIEW

        # For COMMENT previews: assign ticket code now (ticket is "born" on react)
        if was_preview:
            ticket_code = self._generate_ticket_code()
            self.tickets.set_ticket_code(ticket.id, ticket_code)

        self.tickets.mark_reacted(ticket.id, caller_id)
        ticket = self.tickets.get_by_id(ticket.id)  # type: ignore[assignment]

        # Update support message: for previews → full ticket card; for normal → just button
        if ticket.support_group_message_id:
            try:
                dm_url = self._build_dm_url(ticket) if ticket.source_type == SourceType.DIRECT else None
                if was_preview:
                    ticket_text = self._build_ticket_text(ticket)
                    self.sender.edit_message_text(
                        chat_id=self.support_group_chat_id,
                        message_id=ticket.support_group_message_id,
                        text=ticket_text,
                        reply_markup=reacted_keyboard(dm_url),
                    )
                else:
                    self.sender.edit_message_reply_markup(
                        self.support_group_chat_id, ticket.support_group_message_id, reacted_keyboard(dm_url)
                    )
            except Exception as exc:
                logger.warning("could not update react message", extra={"_error": str(exc)})

        # For COMMENT: adopt other previews from this user + write sheets row
        if ticket.source_type == SourceType.COMMENT:
            self._adopt_other_previews(ticket)
            if not self._is_supabase_backend():
                self._sheets_append_initial(ticket)
            ticket = self.tickets.get_by_id(ticket.id)  # type: ignore[assignment]

        # Update Первичная реакция in Sheets
        if not self._is_supabase_backend():
            self._sheets_update_cell(ticket, "G", ticket.reacted_at_utc)

        # Notify user
        notification = (
            f"✅ <b>Ваш запрос принят!</b>\n\n"
            f"Тикет: <b>{ticket.ticket_code}</b>\n"
            f"Специалист уже изучает ваше сообщение. Ожидайте ответ."
        )
        self._safe_send_to_user(ticket, notification)
        logger.info("ticket reacted", extra={"_ticket_id": ticket.id, "_by": caller_id})

    def _handle_close(self, ticket: Ticket, query_id: str, caller_id: int, acknowledge: bool = True) -> None:
        if ticket.status == TicketStatus.CLOSED:
            if acknowledge:
                self._safe_answer_callback(query_id, "Тикет уже закрыт")
            return

        # Answer immediately so the button spinner stops
        if acknowledge:
            self._safe_answer_callback(query_id, "🔒 Тикет закрыт")

        self.tickets.mark_closed(ticket.id, caller_id)
        ticket = self.tickets.get_by_id(ticket.id)  # type: ignore[assignment]

        # Replace ALL "Закрыть тикет" buttons across every "answer_delivered" message
        show_delete = False
        for mid in self.tickets.get_answer_delivered_ids(ticket.id):
            try:
                self.sender.edit_message_reply_markup(
                    self.support_group_chat_id, mid, closed_keyboard(ticket.id, show_delete=show_delete)
                )
            except Exception as exc:
                logger.warning("could not update close button", extra={"_msg_id": mid, "_error": str(exc)})

        # Update Время закрытия in Sheets and mark synced
        if self._is_supabase_backend():
            logger.info("ticket close sheets sync deferred", extra={"_ticket_id": ticket.id})
        else:
            self._sheets_update_cell(ticket, "I", ticket.closed_at_utc)
            self.tickets.mark_sheets_synced(ticket.id)
            self._purge_closed_synced()

        logger.info("ticket closed", extra={"_ticket_id": ticket.id, "_by": caller_id})

    def _handle_delete(self, ticket: Ticket, query_id: str, message_id: int | None, acknowledge: bool = True) -> None:
        if acknowledge:
            self._safe_answer_callback(query_id)

        # Delete replies sent to the user in the community comment thread
        user_reply_ids = self.tickets.get_user_reply_ids(ticket.id)
        for uid in user_reply_ids:
            try:
                self.sender.delete_message(ticket.user_chat_id, uid)
                logger.info("user reply deleted", extra={"_ticket_id": ticket.id, "_msg_id": uid})
            except Exception as exc:
                logger.warning("could not delete user reply", extra={"_ticket_id": ticket.id, "_msg_id": uid, "_error": str(exc)})

        # Replace the delete button with "Удалено" in the support group
        if message_id:
            try:
                self.sender.edit_message_reply_markup(
                    self.support_group_chat_id, message_id, deleted_keyboard()
                )
            except Exception as exc:
                logger.warning("could not update delete button", extra={"_error": str(exc)})

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

    def _send_preview_to_support(self, ticket: Ticket, source_message: NormalizedMessage) -> dict[str, Any]:
        content_type = source_message.content_type
        media_label = CONTENT_LABELS.get(content_type, "")
        text_preview = ""
        if ticket.user_message_text:
            text_preview = f"\n\n<blockquote>{_escape(ticket.user_message_text)}</blockquote>"
        elif media_label:
            text_preview = f"\n{media_label}"

        text = (
            f"📨 <b>Новое сообщение из комментариев</b>\n"
            f"👤 {_escape(ticket.display_name)}"
            f"{text_preview}"
        )
        result = self.sender.send_message(
            chat_id=self.support_group_chat_id,
            text=text,
            reply_markup=react_keyboard(ticket.id),
            message_thread_id=self._support_thread(ticket.source_type),
        )
        if content_type not in (ContentType.TEXT, ContentType.OTHER):
            self._copy_media_to_support(source_message, result.get("result", {}).get("message_id"))
        return result

    def _build_ticket_text(self, ticket: Ticket) -> str:
        source_label = "💬 Комментарий" if ticket.source_type == SourceType.COMMENT else "📩 Директ"
        created_dt = _fmt_dt(ticket.created_at_utc)
        text_preview = ""
        if ticket.user_message_text:
            text_preview = f"\n\n<blockquote>{_escape(ticket.user_message_text)}</blockquote>"
        return (
            f"🎫 <b>Тикет {ticket.ticket_code}</b>\n"
            f"📅 {created_dt}\n"
            f"👤 {_escape(ticket.display_name)}\n"
            f"📍 {source_label}"
            f"{text_preview}"
        )

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

    def _send_reply_to_user(self, ticket: Ticket, answer_text: str) -> int | None:
        text = f"💬 <b>Ответ службы поддержки:</b>\n\n{_escape(answer_text)}"
        return self._safe_send_to_user(ticket, text)

    def _send_answer_delivered(self, ticket: Ticket, answer_text: str) -> dict[str, Any]:
        preview = _escape(answer_text[:300]) + ("…" if len(answer_text) > 300 else "")
        text = (
            f"✅ <b>Ответ доставлен</b>\n"
            f"📋 Тикет: <b>{ticket.ticket_code}</b>\n\n"
            f"💬 <i>{preview}</i>"
        )
        show_delete = ticket.source_type == SourceType.COMMENT
        return self.sender.send_message(
            chat_id=self.support_group_chat_id,
            text=text,
            reply_markup=close_keyboard(ticket.id, show_delete=show_delete),
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

    def _copy_media_to_user(self, ticket: Ticket, message: dict[str, Any]) -> int | None:
        if ticket.source_type == SourceType.DIRECT:
            logger.info("direct user media delivery skipped", extra={"_ticket_id": ticket.id})
            return None
        try:
            kwargs = self._user_delivery_kwargs(ticket)
            result = self.sender.copy_message(
                chat_id=ticket.user_chat_id,
                from_chat_id=self.support_group_chat_id,
                message_id=message["message_id"],
                **kwargs,
            )
            return (result.get("result") or {}).get("message_id")
        except Exception as exc:
            logger.warning("could not copy media to user", extra={"_ticket_id": ticket.id, "_error": str(exc)})
            return None

    def _send_sticker_to_user(self, ticket: Ticket, file_id: str) -> int | None:
        if ticket.source_type == SourceType.DIRECT:
            logger.info("direct user sticker delivery skipped", extra={"_ticket_id": ticket.id})
            return None
        try:
            kwargs = self._user_delivery_kwargs(ticket)
            result = self.sender.send_sticker(chat_id=ticket.user_chat_id, sticker=file_id, **kwargs)
            return (result.get("result") or {}).get("message_id")
        except Exception as exc:
            logger.warning("could not send sticker to user", extra={"_ticket_id": ticket.id, "_error": str(exc)})
            return None

    def _safe_send_to_user(self, ticket: Ticket, text: str) -> int | None:
        if ticket.source_type == SourceType.DIRECT:
            logger.info("direct user message delivery skipped", extra={"_ticket_id": ticket.id})
            return None
        try:
            kwargs = self._user_delivery_kwargs(ticket)
            result = self.sender.send_message(chat_id=ticket.user_chat_id, text=text, **kwargs)
            return (result.get("result") or {}).get("message_id")
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
            return None

    def _user_delivery_kwargs(self, ticket: Ticket) -> dict[str, Any]:
        if ticket.source_type == SourceType.COMMENT:
            kwargs: dict[str, Any] = {"reply_to_message_id": ticket.user_message_id}
            if ticket.user_message_thread_id:
                kwargs["message_thread_id"] = ticket.user_message_thread_id
            return kwargs

        topic_id = getattr(ticket, "user_direct_messages_topic_id", None) or ticket.user_message_thread_id
        if topic_id:
            return {"message_thread_id": topic_id}
        return {}

    def _adopt_other_previews(self, ticket: Ticket) -> None:
        """Convert later previews to continuations; silently close earlier ones."""
        previews = self.tickets.get_previews_for_user(ticket.user_id, ticket.user_chat_id, exclude_id=ticket.id)
        for preview in previews:
            if preview.id > ticket.id and preview.support_group_message_id:
                # Message came after the reacted one → show as continuation
                try:
                    text_preview = ""
                    if preview.user_message_text:
                        text_preview = f"\n\n<blockquote>{_escape(preview.user_message_text)}</blockquote>"
                    msg = (
                        f"📨 <b>Новое сообщение по тикету {ticket.ticket_code}</b>\n"
                        f"👤 {_escape(ticket.display_name)}"
                        f"{text_preview}"
                    )
                    self.sender.edit_message_text(
                        chat_id=self.support_group_chat_id,
                        message_id=preview.support_group_message_id,
                        text=msg,
                        reply_markup={"inline_keyboard": []},
                    )
                    self.tickets.track_message(ticket.id, "continuation", preview.support_group_message_id)
                except Exception as exc:
                    logger.warning("could not adopt preview", extra={"_preview_id": preview.id, "_error": str(exc)})
            # Both earlier and later previews are closed (absorbed into this ticket)
            self.tickets.close_preview(preview.id)
        self._purge_closed_synced()

    def _sheets_append_initial(self, ticket: Ticket) -> None:
        try:
            row = build_initial_ticket_row(ticket, self.tz_offset)
            row_number = self.sheets.append_ticket_row(row)
            if row_number:
                self.tickets.set_sheets_row_number(ticket.id, row_number)
                try:
                    self.sheets.color_source_cells(row_number, ticket.source_type)
                except Exception as exc:
                    logger.warning("could not color source cells", extra={"_ticket_id": ticket.id, "_error": str(exc)})
            logger.info("ticket row appended to sheets", extra={"_ticket_id": ticket.id, "_row": row_number})
        except Exception as exc:
            logger.error("ticket initial sheets write failed", extra={"_ticket_id": ticket.id, "_error": str(exc)})

    def _sheets_update_cell(self, ticket: Ticket, col: str, iso_value: str | None) -> None:
        if not ticket.sheets_row_number:
            return
        try:
            from app.sheets.ticket_rows import _fmt_time
            value = _fmt_time(iso_value, self.tz_offset)
            self.sheets.update_ticket_cell(ticket.sheets_row_number, col, value)
        except Exception as exc:
            logger.warning(
                "could not update sheets cell",
                extra={"_ticket_id": ticket.id, "_col": col, "_error": str(exc)},
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

        if self.day_start_hour <= hour < self.night_start_hour:
            # Day shift: 08:00 → 20:00 today
            shift = "D"
            shift_start = datetime.combine(now_local.date(), time(self.day_start_hour, 0), tzinfo=tz)
            shift_end = datetime.combine(now_local.date(), time(self.night_start_hour, 0), tzinfo=tz)
        elif hour >= self.night_start_hour:
            # Night shift just started: 20:00 today → 08:00 tomorrow
            shift = "N"
            shift_start = datetime.combine(now_local.date(), time(self.night_start_hour, 0), tzinfo=tz)
            shift_end = datetime.combine(now_local.date() + timedelta(days=1), time(self.day_start_hour, 0), tzinfo=tz)
        else:
            # Early morning: still in last night's shift (20:00 yesterday → 08:00 today)
            shift = "N"
            yesterday = now_local.date() - timedelta(days=1)
            shift_start = datetime.combine(yesterday, time(self.night_start_hour, 0), tzinfo=tz)
            shift_end = datetime.combine(now_local.date(), time(self.day_start_hour, 0), tzinfo=tz)

        counter_key = f"{shift}{shift_start.strftime('%d%m')}"
        utc_start = shift_start.astimezone(timezone.utc).isoformat()
        utc_end = shift_end.astimezone(timezone.utc).isoformat()

        return self.tickets.next_ticket_code(counter_key, shift, utc_start, utc_end)

    def _purge_closed_synced(self) -> int:
        purge = getattr(self.tickets, "purge_closed_synced", None)
        if not purge:
            return 0
        try:
            deleted = int(purge())
            if deleted:
                logger.info("closed synced tickets purged", extra={"_deleted": deleted})
            return deleted
        except Exception as exc:
            logger.warning("closed ticket purge failed", extra={"_error": str(exc)}, exc_info=True)
            return 0

    def _is_supabase_backend(self) -> bool:
        return self.tickets.__class__.__name__ == "PostgresTicketRepository"


def _escape(text: str | None) -> str:
    if not text:
        return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt_dt(iso: str) -> str:
    try:
        if isinstance(iso, datetime):
            dt = iso
        else:
            dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%d.%m.%Y %H:%M UTC")
    except Exception:
        return str(iso)


def _ticket_label(ticket: Ticket) -> str:
    return ticket.ticket_code or f"preview#{ticket.id}"


def _status_label(status: str) -> str:
    if status == TicketStatus.PREVIEW:
        return "ожидает первичной реакции"
    if status == TicketStatus.NEW:
        return "ожидает первичной реакции"
    if status == TicketStatus.REACTED:
        return "ожидает вторичной реакции"
    if status == TicketStatus.ANSWERED:
        return "ожидает закрытия"
    if status == TicketStatus.CLOSED:
        return "закрыт"
    return status
