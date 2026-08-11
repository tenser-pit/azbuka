import logging
import traceback
from typing import TYPE_CHECKING

from aiogram import Bot

from app.config import Settings
from app.max.client import MaxClient

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

MAX_TELEGRAM_MESSAGE_LENGTH = 4000


class ErrorReporter:
    def __init__(
        self,
        settings: Settings,
        telegram_bot: Bot | None,
        max_client: MaxClient | None = None,
    ):
        self.settings = settings
        self.telegram_bot = telegram_bot
        self.max_client = max_client

    @property
    def recipient_ids(self) -> list[int]:
        if self.settings.error_notify_telegram_ids:
            return self.settings.error_notify_telegram_ids
        return self.settings.admin_telegram_ids

    async def report_error(
        self,
        source: str,
        error: BaseException,
        *,
        request_path: str | None = None,
        extra: str | None = None,
    ) -> None:
        logger.error(
            "Internal server error [source=%s, path=%s]: %s",
            source,
            request_path or "-",
            error,
            exc_info=True,
        )

        if not self.settings.error_notify_enabled:
            logger.info(
                "Error notification skipped (ERROR_NOTIFY_ENABLED=false): source=%s",
                source,
            )
            return

        message_text = self._format_message(
            source=source,
            error=error,
            request_path=request_path,
            extra=extra,
        )

        sent_count = 0
        if self.max_client is not None:
            for chat_id in self.settings.admin_max_ids:
                try:
                    await self.max_client.send_message_to_user(chat_id, message_text, format=None)
                    sent_count += 1
                except Exception as send_error:
                    logger.exception(
                        "Failed to deliver MAX error notification to chat_id=%s: %s",
                        chat_id,
                        send_error,
                    )

        recipient_ids = self.recipient_ids
        if self.telegram_bot is not None and self.settings.is_telegram_enabled:
            for chat_id in recipient_ids:
                try:
                    await self.telegram_bot.send_message(chat_id, message_text)
                    sent_count += 1
                    logger.info(
                        "Error notification delivered to chat_id=%s (source=%s)",
                        chat_id,
                        source,
                    )
                except Exception as send_error:
                    logger.exception(
                        "Failed to deliver error notification to chat_id=%s (source=%s): %s",
                        chat_id,
                        source,
                        send_error,
                    )

        if sent_count == 0:
            logger.error(
                "Error notification failed for all recipients (source=%s)",
                source,
            )
        else:
            logger.info(
                "Error notification summary: sent=%d, source=%s",
                sent_count,
                source,
            )

    def _format_message(
        self,
        source: str,
        error: BaseException,
        request_path: str | None,
        extra: str | None,
    ) -> str:
        traceback_text = "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )
        lines = [
            "🚨 HTTP 500 — внутренняя ошибка",
            "",
            f"Источник: {source}",
        ]
        if request_path:
            lines.append(f"Путь: {request_path}")
        if extra:
            lines.append(f"Контекст: {extra}")
        lines.extend(["", f"Ошибка: {type(error).__name__}: {error}", "", "Traceback:", traceback_text])

        message_text = "\n".join(lines)
        if len(message_text) > MAX_TELEGRAM_MESSAGE_LENGTH:
            truncated = message_text[: MAX_TELEGRAM_MESSAGE_LENGTH - 20]
            message_text = f"{truncated}\n\n... (обрезано)"
        return message_text


def scheduled_job_guard(
    error_reporter: ErrorReporter,
    source: str,
) -> "Callable[[Callable[..., Awaitable[None]]], Callable[..., Awaitable[None]]]":
    def decorator(job: "Callable[..., Awaitable[None]]") -> "Callable[..., Awaitable[None]]":
        async def wrapper() -> None:
            try:
                await job()
            except Exception as error:
                await error_reporter.report_error(source, error)

        return wrapper

    return decorator


async def aiohttp_error_middleware(error_reporter: ErrorReporter, request, handler):
    from aiohttp import web

    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception as error:
        await error_reporter.report_error(
            source="aiohttp",
            error=error,
            request_path=request.path,
        )
        return web.json_response({"error": "internal server error"}, status=500)
