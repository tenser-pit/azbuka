import logging
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import PendingMaxChat
from app.max.admin import MaxAdminHandler
from app.max.client import MaxClient
from app.services.reports import ReportService

logger = logging.getLogger(__name__)

VIDEO_ATTACHMENT_TYPES = {"video", "file", "media"}


def extract_message_payload(update: dict[str, Any]) -> dict[str, Any] | None:
    message = update.get("message")
    if message is None:
        return None

    body = message.get("body") or {}
    sender = message.get("sender") or {}
    recipient = message.get("recipient") or {}

    chat_id = recipient.get("chat_id")
    if chat_id is None:
        chat_id = update.get("chat_id")

    return {
        "message_id": message.get("message_id") or message.get("id") or body.get("mid"),
        "sender_user_id": sender.get("user_id"),
        "chat_id": chat_id,
        "text": body.get("text") or "",
        "has_video": _message_has_video(body),
    }


def extract_callback_payload(update: dict[str, Any]) -> dict[str, Any] | None:
    callback = update.get("callback") or {}
    user = callback.get("user") or update.get("user") or {}
    message = callback.get("message") or update.get("message") or {}
    recipient = message.get("recipient") or {}

    payload = callback.get("payload")
    if payload is None:
        return None

    chat_id = recipient.get("chat_id") or update.get("chat_id")
    user_id = user.get("user_id")
    return {
        "payload": str(payload),
        "user_id": user_id,
        "chat_id": chat_id,
        "callback_id": callback.get("callback_id") or callback.get("id"),
    }


def _message_has_video(body: dict[str, Any]) -> bool:
    attachments = body.get("attachments") or []
    for attachment in attachments:
        attachment_type = str(attachment.get("type", "")).lower()
        if attachment_type in VIDEO_ATTACHMENT_TYPES:
            payload = attachment.get("payload") or {}
            if attachment_type == "file":
                mime_type = str(payload.get("mime_type", "")).lower()
                if mime_type.startswith("video/"):
                    return True
            else:
                return True
    return False


class MaxWebhookHandler:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        notify_admin_callback,
        max_client: MaxClient,
        fsm_storage: dict[int, dict[str, Any]],
    ):
        self.session = session
        self.settings = settings
        self.notify_admin_callback = notify_admin_callback
        self.max_client = max_client
        self.fsm_storage = fsm_storage
        self.admin_handler = MaxAdminHandler(session, settings, max_client, fsm_storage)

    async def handle_update(self, update: dict[str, Any]) -> None:
        update_type = update.get("update_type") or update.get("type")
        logger.info("MAX update received: %s", update_type)

        if update_type == "bot_added":
            await self._handle_bot_added(update)
            return

        if update_type == "message_callback":
            await self._handle_message_callback(update)
            return

        if update_type == "message_created":
            await self._handle_message_created(update)
            return

    async def _handle_bot_added(self, update: dict[str, Any]) -> None:
        chat_id = update.get("chat_id")
        if chat_id is None:
            return

        title = update.get("chat_title") or update.get("title") or f"Чат {chat_id}"
        stmt = (
            insert(PendingMaxChat)
            .values(
                max_chat_id=chat_id,
                title=title,
                added_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_nothing(index_elements=["max_chat_id"])
        )
        await self.session.execute(stmt)
        await self.session.commit()

        if self.notify_admin_callback is not None:
            await self.notify_admin_callback(
                f"Новый чат в MAX: {title}\nID: {chat_id}\nПривяжите через /bind_chat"
            )

    async def _handle_message_callback(self, update: dict[str, Any]) -> None:
        payload = extract_callback_payload(update)
        if payload is None or payload.get("user_id") is None:
            return
        await self.admin_handler.handle_callback(
            user_id=int(payload["user_id"]),
            chat_id=int(payload["chat_id"]) if payload.get("chat_id") is not None else None,
            payload=str(payload["payload"]),
            callback_id=payload.get("callback_id"),
        )

    async def _handle_message_created(self, update: dict[str, Any]) -> None:
        payload = extract_message_payload(update)
        if payload is None:
            return

        chat_id = payload.get("chat_id")
        sender_user_id = payload.get("sender_user_id")
        message_id = payload.get("message_id")
        text = str(payload.get("text", ""))

        if sender_user_id is None:
            logger.debug("Incomplete message payload: %s", payload)
            return

        admin_handled = await self.admin_handler.handle_message(
            user_id=int(sender_user_id),
            chat_id=int(chat_id) if chat_id is not None else None,
            text=text,
        )
        if admin_handled:
            return

        if chat_id is None or message_id is None:
            logger.debug("Incomplete message payload for report: %s", payload)
            return

        report_service = ReportService(self.session, self.settings)
        accepted = await report_service.process_incoming_message(
            max_chat_id=int(chat_id),
            sender_user_id=int(sender_user_id),
            message_id=int(message_id) if str(message_id).isdigit() else hash(str(message_id)) % (10**12),
            message_text=text,
            has_video=bool(payload.get("has_video")),
            report_date=date.today(),
        )
        if accepted:
            logger.info("Report accepted for chat %s", chat_id)

    async def list_pending_chats(self) -> list[PendingMaxChat]:
        result = await self.session.execute(
            select(PendingMaxChat).order_by(PendingMaxChat.added_at.desc())
        )
        return list(result.scalars().all())
