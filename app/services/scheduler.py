import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.config import APP_TIMEZONE, Settings
from app.max.client import MaxClient
from app.services.error_reporter import ErrorReporter, scheduled_job_guard
from app.services.notifications import NotificationService

logger = logging.getLogger(__name__)


def setup_scheduler(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    telegram_bot: Bot | None,
    max_client: MaxClient,
    error_reporter: ErrorReporter,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=APP_TIMEZONE)
    notifications = NotificationService(session_factory, settings, telegram_bot, max_client)

    def guard(job, source: str):
        return scheduled_job_guard(error_reporter, source)(job)

    async def midmonth_summary() -> None:
        await notifications.send_monthly_summary("15-е число — сводка штрафов")

    async def endmonth_summary() -> None:
        await notifications.send_monthly_summary("Последний день месяца — сводка штрафов")

    scheduler.add_job(
        guard(notifications.send_trainers_chat_reminder, "scheduler:trainers_chat_reminder"),
        trigger="cron",
        hour=22,
        minute=0,
        id="trainers_chat_reminder",
        replace_existing=True,
    )
    scheduler.add_job(
        guard(notifications.apply_and_notify_daily_penalties, "scheduler:daily_penalties"),
        trigger="cron",
        hour=23,
        minute=59,
        id="daily_penalties",
        replace_existing=True,
    )
    scheduler.add_job(
        guard(notifications.apply_and_notify_video_penalties, "scheduler:video_penalties"),
        trigger="cron",
        day_of_week="sat",
        hour=13,
        minute=0,
        id="video_penalties",
        replace_existing=True,
    )
    scheduler.add_job(
        guard(midmonth_summary, "scheduler:midmonth_summary"),
        trigger="cron",
        day=15,
        hour=9,
        minute=0,
        id="midmonth_summary",
        replace_existing=True,
    )
    scheduler.add_job(
        guard(endmonth_summary, "scheduler:endmonth_summary"),
        trigger="cron",
        day="last",
        hour=9,
        minute=0,
        id="endmonth_summary",
        replace_existing=True,
    )

    return scheduler
