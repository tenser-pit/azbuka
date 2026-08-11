import asyncio
import logging
from typing import Any

from aiohttp import web
from aiogram import Bot

from app.config import get_settings
from app.db.session import async_session_factory
from app.max.client import MaxClient
from app.max.webhook import MaxWebhookHandler
from app.services.error_reporter import ErrorReporter, aiohttp_error_middleware
from app.services.notifications import NotificationService
from app.services.scheduler import setup_scheduler
from app.telegram.bot import create_dispatcher
from app.telegram.error_handler import register_telegram_error_handler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAX_ADMIN_FSM: dict[int, dict[str, Any]] = {}


async def create_max_webhook_app(
    settings,
    notification_service: NotificationService,
    error_reporter: ErrorReporter,
    max_client: MaxClient,
) -> web.Application:
    async def notify_admins(text: str) -> None:
        await notification_service.notify_admins(text)

    async def handle_max_webhook(request: web.Request) -> web.Response:
        try:
            update = await request.json()
        except Exception as error:
            logger.exception("Invalid MAX webhook payload")
            await error_reporter.report_error(
                source="max_webhook:invalid_payload",
                error=error,
                request_path=request.path,
            )
            return web.Response(status=400)

        async with async_session_factory() as session:
            handler = MaxWebhookHandler(
                session,
                settings,
                notify_admins,
                max_client,
                MAX_ADMIN_FSM,
            )
            await handler.handle_update(update)
        return web.Response(status=200)

    @web.middleware
    async def error_middleware(request: web.Request, handler):
        return await aiohttp_error_middleware(error_reporter, request, handler)

    application = web.Application(middlewares=[error_middleware])
    application.router.add_post("/max/webhook", handle_max_webhook)
    return application


async def main() -> None:
    settings = get_settings()
    if not settings.max_bot_token:
        raise RuntimeError("MAX_BOT_TOKEN is required")

    telegram_bot: Bot | None = None
    if settings.is_telegram_enabled:
        telegram_bot = Bot(token=settings.telegram_bot_token)
        logger.info("Telegram backup enabled")
    elif settings.telegram_enabled and not settings.telegram_bot_token:
        logger.warning("TELEGRAM_ENABLED=true, but TELEGRAM_BOT_TOKEN is empty; Telegram disabled")
    else:
        logger.info("Telegram backup disabled (TELEGRAM_ENABLED=false)")

    max_client = MaxClient(settings)
    error_reporter = ErrorReporter(settings, telegram_bot, max_client)
    notification_service = NotificationService(
        async_session_factory, settings, telegram_bot, max_client
    )

    scheduler = setup_scheduler(
        async_session_factory, settings, telegram_bot, max_client, error_reporter
    )
    scheduler.start()

    if settings.error_notify_enabled:
        logger.info(
            "Error notifications enabled for chat_ids=%s",
            error_reporter.recipient_ids or "none",
        )
    else:
        logger.info("Error notifications disabled (ERROR_NOTIFY_ENABLED=false)")

    if settings.webhook_base_url:
        webhook_url = f"{settings.webhook_base_url.rstrip('/')}/max/webhook"
        subscribed = await max_client.subscribe_webhook(webhook_url)
        if subscribed:
            logger.info("MAX webhook subscribed: %s", webhook_url)
        else:
            logger.warning("Failed to subscribe MAX webhook")
    else:
        logger.warning("WEBHOOK_BASE_URL is empty; MAX subscription skipped")

    webhook_app = await create_max_webhook_app(
        settings, notification_service, error_reporter, max_client
    )
    runner = web.AppRunner(webhook_app)
    await runner.setup()
    site = web.TCPSite(runner, settings.webhook_host, settings.webhook_port)
    await site.start()
    logger.info("MAX webhook listening on %s:%s", settings.webhook_host, settings.webhook_port)

    try:
        if telegram_bot is not None:
            dispatcher = create_dispatcher(async_session_factory, settings)
            register_telegram_error_handler(dispatcher, error_reporter)
            try:
                await dispatcher.start_polling(telegram_bot)
            except Exception:
                logger.exception("Telegram polling failed; continuing in MAX-only mode")
                await asyncio.Event().wait()
        else:
            await asyncio.Event().wait()
    finally:
        scheduler.shutdown(wait=False)
        await runner.cleanup()
        if telegram_bot is not None:
            await telegram_bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
