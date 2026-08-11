import logging

from aiogram import Dispatcher
from aiogram.types import ErrorEvent

from app.services.error_reporter import ErrorReporter

logger = logging.getLogger(__name__)


def register_telegram_error_handler(
    dispatcher: Dispatcher,
    error_reporter: ErrorReporter,
) -> None:
    @dispatcher.errors()
    async def handle_telegram_error(event: ErrorEvent) -> None:
        exception = event.exception
        update = event.update
        update_type = update.event_type if update else "unknown"
        logger.error("Unhandled aiogram error [update_type=%s]", update_type, exc_info=exception)
        await error_reporter.report_error(
            source="aiogram",
            error=exception,
            extra=f"update_type={update_type}",
        )
