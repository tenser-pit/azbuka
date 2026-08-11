import logging
from datetime import date

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.db.enums import ReportStatus
from app.db.models import DailyReport, Penalty
from app.max.client import MaxClient
from app.services.penalties import PenaltyService
from app.services.reports import ReportService

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        telegram_bot: Bot | None,
        max_client: MaxClient,
    ):
        self.session_factory = session_factory
        self.settings = settings
        self.telegram_bot = telegram_bot
        self.max_client = max_client

    async def notify_admins(self, text: str) -> None:
        for admin_id in self.settings.admin_max_id_set:
            try:
                await self.max_client.send_message_to_user(admin_id, text, format=None)
            except Exception:
                logger.exception("Failed to notify MAX admin %s", admin_id)

        if self.telegram_bot is None or not self.settings.is_telegram_enabled:
            return

        for admin_id in self.settings.admin_ids:
            try:
                await self.telegram_bot.send_message(admin_id, text)
            except Exception:
                logger.exception("Failed to notify Telegram admin %s", admin_id)

    async def send_evening_reminders(self) -> None:
        await self.send_trainers_chat_reminder()

    async def send_trainers_chat_reminder(self) -> None:
        trainers_chat_id = self.settings.trainers_max_chat_id
        if trainers_chat_id is None:
            logger.warning("TRAINERS_MAX_CHAT_ID is not set; skip 22:00 reminder")
            await self.notify_admins(
                "22:00 — не удалось отправить напоминание: TRAINERS_MAX_CHAT_ID не задан"
            )
            return

        async with self.session_factory() as session:
            report_service = ReportService(session, self.settings)
            expected = await report_service.get_expected_reports(date.today())

            location_ids = [item.location.id for item in expected]
            reports_result = await session.execute(
                select(DailyReport).where(
                    DailyReport.report_date == date.today(),
                    DailyReport.location_id.in_(location_ids),
                    DailyReport.status == ReportStatus.SUBMITTED,
                )
            )
            submitted_ids = {report.location_id for report in reports_result.scalars().all()}

            missing_by_trainer: dict[int, list[str]] = {}
            trainer_meta: dict[int, tuple[str, int, str | None]] = {}

            for item in expected:
                if item.location.id in submitted_ids:
                    continue
                trainer = item.trainer
                missing_by_trainer.setdefault(trainer.id, []).append(item.location.name)
                trainer_meta[trainer.id] = (
                    trainer.name,
                    trainer.max_user_id,
                    trainer.max_username,
                )

            if not missing_by_trainer:
                chat_text = "✅ Все сдали. Молодцы!"
                admin_text = "22:00 — все отчёты сданы."
            else:
                lines = ["⚠️ Не сданы отчёты! Тренеры, срочно:"]
                admin_lines = ["22:00 — не сдали отчёт:"]
                for trainer_id, locations in missing_by_trainer.items():
                    name, max_user_id, max_username = trainer_meta[trainer_id]
                    locations_text = ", ".join(locations)
                    mention = f"[{name}](max://user/{max_user_id})"
                    username_part = f"@{max_username} " if max_username else ""
                    lines.append(
                        f"{mention} {username_part}({name}) — {locations_text}"
                    )
                    admin_lines.append(f"{name} — {locations_text}")
                chat_text = "\n".join(lines)
                admin_text = "\n".join(admin_lines)

            await self.max_client.send_message_to_chat(
                trainers_chat_id,
                chat_text,
                format="markdown",
            )
            await self.notify_admins(admin_text)

    async def apply_and_notify_daily_penalties(self) -> None:
        async with self.session_factory() as session:
            penalty_service = PenaltyService(session, self.settings)
            penalties = await penalty_service.apply_daily_penalties(date.today())
            await self._notify_penalties("23:59 — начислены штрафы за отчёты", penalties)

    async def apply_and_notify_video_penalties(self) -> None:
        async with self.session_factory() as session:
            penalty_service = PenaltyService(session, self.settings)
            penalties = await penalty_service.apply_video_penalties(date.today())
            await self._notify_penalties("Суббота 13:00 — штрафы за видео", penalties)

    async def send_monthly_summary(self, title: str) -> None:
        today = date.today()
        async with self.session_factory() as session:
            penalty_service = PenaltyService(session, self.settings)
            start_date = date(today.year, today.month, 1)
            summary = await penalty_service.get_summary(start_date, today)

            if not summary:
                await self.notify_admins(f"{title}\nШтрафов за месяц нет.")
                return

            lines = [title, ""]
            for trainer, count, total in summary:
                lines.append(f"{trainer.name}: {count} штр., сумма {total} ₽")
            await self.notify_admins("\n".join(lines))

    async def _notify_penalties(self, title: str, penalties: list[Penalty]) -> None:
        if not penalties:
            await self.notify_admins(f"{title}\nНовых штрафов нет.")
            return

        async with self.session_factory() as session:
            penalty_ids = [penalty.id for penalty in penalties]
            result = await session.execute(
                select(Penalty)
                .where(Penalty.id.in_(penalty_ids))
                .options(selectinload(Penalty.trainer), selectinload(Penalty.location))
            )
            loaded = list(result.scalars().all())

        lines = [title, ""]
        for penalty in loaded:
            lines.append(
                f"#{penalty.id} {penalty.trainer.name} — {penalty.location.name}: "
                f"{penalty.amount} ₽ ({penalty.reason.value})"
            )
        await self.notify_admins("\n".join(lines))
