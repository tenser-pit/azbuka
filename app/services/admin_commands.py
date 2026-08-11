from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.db.models import PendingMaxChat, Trainer, TrainerAssignment
from app.services.penalties import PenaltyService
from app.services.reports import ReportService
from app.services.salary import (
    SalaryService,
    current_month_period,
    current_salary_period,
    current_week_period,
)
from app.telegram.keyboards import format_weekdays


class AdminCommandService:
    def __init__(self, session: AsyncSession, settings: Settings):
        self.session = session
        self.settings = settings
        self.report_service = ReportService(session, settings)
        self.penalty_service = PenaltyService(session, settings)
        self.salary_service = SalaryService(session, settings)

    def start_menu_text(self) -> str:
        return (
            "Панель мониторинга отчётов.\n\n"
            "/status — статус сегодня\n"
            "/week — статистика недели\n"
            "/month — статистика месяца\n"
            "/salary — зарплата за период\n"
            "/stats — штрафы/статистика месяца\n"
            "/remove_penalty — активные штрафы\n"
            "/pending_chats — непривязанные чаты\n"
            "/bind_chat — привязать чат\n"
            "/bind_trainer — привязать тренера\n"
            "/assignments — связи\n"
            "/trainers — тренеры\n"
            "Отменить рабочий день — через меню / day-off"
        )

    async def status_text(self, report_date: date | None = None) -> str:
        if report_date is None:
            report_date = date.today()
        lines = await self.report_service.get_today_status_lines(report_date)
        return "Статус на сегодня:\n" + "\n".join(lines)

    async def week_text(self, today: date | None = None) -> str:
        start_date, end_date = current_week_period(today)
        lines = await self.salary_service.format_period_stats(
            start_date, end_date, "Статистика за неделю"
        )
        return "\n".join(lines)

    async def month_text(self, today: date | None = None) -> str:
        start_date, end_date = current_month_period(today)
        lines = await self.salary_service.format_period_stats(
            start_date, end_date, "Статистика за месяц"
        )
        return "\n".join(lines)

    async def salary_text(self, today: date | None = None) -> str:
        start_date, end_date = current_salary_period(today)
        lines = await self.salary_service.format_salary_lines(start_date, end_date)
        return "\n".join(lines).rstrip()

    async def summary_text(self, start_date: date, end_date: date) -> str:
        summary = await self.penalty_service.get_summary(start_date, end_date)
        if not summary:
            return "Штрафов за период нет."
        lines = [
            f"Штрафы {start_date:%d.%m.%Y} — {end_date:%d.%m.%Y}:",
            "",
        ]
        for trainer, count, total in summary:
            lines.append(f"{trainer.name}: {count} штр., сумма {total} ₽")
        return "\n".join(lines)

    async def stats_text(self, today: date | None = None) -> str:
        if today is None:
            today = date.today()
        stats = await self.penalty_service.get_month_stats(today.year, today.month)
        return (
            f"Статистика за {today.month:02d}.{today.year}:\n"
            f"Сдано: {stats['submitted']}\n"
            f"Пропущено: {stats['missed']}\n"
            f"Отменено: {stats['excused']}\n"
            f"% сдачи: {stats['submit_rate']}\n"
            f"Штрафов: {stats['penalty_count']}, сумма {stats['penalty_sum']} ₽"
        )

    async def active_penalties_text(self) -> str:
        penalties = await self.penalty_service.get_active_penalties()
        if not penalties:
            return "Активных штрафов нет."
        lines = ["Активные штрафы (снять: /rm_ID):", ""]
        for penalty in penalties:
            lines.append(
                f"/rm_{penalty.id} — {penalty.trainer.name}, {penalty.location.name}, "
                f"{penalty.amount} ₽, {penalty.reason.value}, {penalty.penalty_date:%d.%m.%Y}"
            )
        return "\n".join(lines)

    async def remove_penalty(self, penalty_id: int, removed_by: int) -> str:
        penalty = await self.penalty_service.remove_penalty(penalty_id, removed_by)
        if penalty is None:
            return "Штраф не найден или уже снят."
        return f"Штраф #{penalty_id} снят."

    async def pending_chats_text(self) -> str:
        result = await self.session.execute(
            select(PendingMaxChat).order_by(PendingMaxChat.added_at.desc())
        )
        pending = list(result.scalars().all())
        if not pending:
            return "Непривязанных чатов нет."
        lines = ["Непривязанные MAX-чаты:", ""]
        for chat in pending:
            lines.append(f"• {chat.title} (id: {chat.max_chat_id})")
        lines.append("\nПривязать: /bind_chat")
        return "\n".join(lines)

    async def assignments_text(self) -> str:
        result = await self.session.execute(
            select(TrainerAssignment)
            .where(TrainerAssignment.is_active.is_(True))
            .options(
                selectinload(TrainerAssignment.trainer),
                selectinload(TrainerAssignment.location),
            )
            .order_by(TrainerAssignment.id)
        )
        assignments = list(result.scalars().all())
        if not assignments:
            return "Связи тренер–локация не настроены."
        lines = ["Связи тренер–локация:", ""]
        for assignment in assignments:
            lines.append(
                f"#{assignment.id} {assignment.trainer.name} → {assignment.location.name} "
                f"({format_weekdays(assignment.weekdays)})"
            )
        lines.append("\nДеактивировать: /unassign ID")
        return "\n".join(lines)

    async def unassign(self, assignment_id: int) -> str:
        result = await self.session.execute(
            select(TrainerAssignment).where(TrainerAssignment.id == assignment_id)
        )
        assignment = result.scalar_one_or_none()
        if assignment is None:
            return "Связь не найдена."
        assignment.is_active = False
        await self.session.commit()
        return f"Связь #{assignment_id} деактивирована."

    async def trainers_text(self) -> str:
        result = await self.session.execute(select(Trainer).order_by(Trainer.id))
        trainers = list(result.scalars().all())
        if not trainers:
            return "Тренеры не найдены."
        lines = ["Тренеры:", ""]
        for trainer in trainers:
            telegram_id = trainer.telegram_user_id or "не задан"
            max_username = f"@{trainer.max_username}" if trainer.max_username else "не задан"
            lines.append(
                f"#{trainer.id} {trainer.name} — MAX id: {trainer.max_user_id}, "
                f"username: {max_username}, TG: {telegram_id}"
            )
        lines.append("\n/set_trainer_max ID USERNAME")
        lines.append("/set_trainer_tg ID TG_ID")
        return "\n".join(lines)

    async def set_trainer_tg(self, trainer_id: int, telegram_id: int) -> str:
        result = await self.session.execute(select(Trainer).where(Trainer.id == trainer_id))
        trainer = result.scalar_one_or_none()
        if trainer is None:
            return "Тренер не найден."
        trainer.telegram_user_id = telegram_id
        await self.session.commit()
        return f"Telegram ID {telegram_id} привязан к {trainer.name}."

    async def set_trainer_max_username(self, trainer_id: int, max_username: str) -> str:
        result = await self.session.execute(select(Trainer).where(Trainer.id == trainer_id))
        trainer = result.scalar_one_or_none()
        if trainer is None:
            return "Тренер не найден."
        cleaned = max_username.lstrip("@").strip()
        if not cleaned:
            return "Укажите username."
        trainer.max_username = cleaned
        await self.session.commit()
        return f"MAX username @{cleaned} привязан к {trainer.name}."

    @staticmethod
    def parse_summary_args(args: str | None) -> tuple[date, date] | str:
        if not args:
            return "Использование: /summary дд.мм.гггг дд.мм.гггг"
        parts = args.split()
        if len(parts) != 2:
            return "Использование: /summary дд.мм.гггг дд.мм.гггг"
        try:
            start_date = datetime.strptime(parts[0], "%d.%m.%Y").date()
            end_date = datetime.strptime(parts[1], "%d.%m.%Y").date()
        except ValueError:
            return "Неверный формат даты. Пример: /summary 01.06.2026 21.06.2026"
        return start_date, end_date
