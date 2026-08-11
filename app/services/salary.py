from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.db.enums import PhoneSource, ReportStatus
from app.db.models import DailyReport, ReportPhone, Trainer
from app.services.reports import ReportService


@dataclass(frozen=True)
class TrainerSalary:
    trainer: Trainer
    trial_count: int
    outreach_count: int
    amount: int
    phones: list[ReportPhone]


def current_salary_period(today: date | None = None) -> tuple[date, date]:
    if today is None:
        today = date.today()
    if today.day <= 15:
        return date(today.year, today.month, 1), date(today.year, today.month, 15)
    last_day = monthrange(today.year, today.month)[1]
    return date(today.year, today.month, 16), date(today.year, today.month, last_day)


def current_week_period(today: date | None = None) -> tuple[date, date]:
    if today is None:
        today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    return week_start, week_end


def current_month_period(today: date | None = None) -> tuple[date, date]:
    if today is None:
        today = date.today()
    last_day = monthrange(today.year, today.month)[1]
    return date(today.year, today.month, 1), date(today.year, today.month, last_day)


class SalaryService:
    def __init__(self, session: AsyncSession, settings: Settings):
        self.session = session
        self.settings = settings
        self.report_service = ReportService(session, settings)

    async def get_trainer_salaries(
        self,
        start_date: date,
        end_date: date,
    ) -> list[TrainerSalary]:
        result = await self.session.execute(
            select(ReportPhone)
            .join(DailyReport)
            .where(
                DailyReport.report_date >= start_date,
                DailyReport.report_date <= end_date,
                DailyReport.status == ReportStatus.SUBMITTED,
            )
            .options(
                selectinload(ReportPhone.trainer),
            )
            .order_by(ReportPhone.trainer_id, ReportPhone.id)
        )
        phones = list(result.scalars().all())

        by_trainer: dict[int, list[ReportPhone]] = {}
        trainers: dict[int, Trainer] = {}
        for phone in phones:
            by_trainer.setdefault(phone.trainer_id, []).append(phone)
            trainers[phone.trainer_id] = phone.trainer

        salaries: list[TrainerSalary] = []
        for trainer_id, trainer_phones in by_trainer.items():
            trial_count = sum(
                1 for phone in trainer_phones if phone.source == PhoneSource.TRIAL
            )
            outreach_count = sum(
                1 for phone in trainer_phones if phone.source == PhoneSource.OUTREACH
            )
            amount = (
                trial_count * self.settings.salary_trial_rate
                + outreach_count * self.settings.salary_outreach_rate
            )
            salaries.append(
                TrainerSalary(
                    trainer=trainers[trainer_id],
                    trial_count=trial_count,
                    outreach_count=outreach_count,
                    amount=amount,
                    phones=trainer_phones,
                )
            )
        salaries.sort(key=lambda item: item.trainer.name)
        return salaries

    async def format_salary_lines(
        self,
        start_date: date,
        end_date: date,
    ) -> list[str]:
        salaries = await self.get_trainer_salaries(start_date, end_date)
        lines = [
            f"Зарплата {start_date:%d.%m.%Y} — {end_date:%d.%m.%Y}:",
            "",
        ]
        if not salaries:
            lines.append("Номеров за период нет.")
            return lines

        for salary in salaries:
            lines.append(
                f"{salary.trainer.name}: {salary.amount} ₽ "
                f"(пробный {salary.trial_count}×{self.settings.salary_trial_rate}, "
                f"общение {salary.outreach_count}×{self.settings.salary_outreach_rate})"
            )
            for phone in salary.phones:
                lines.append(
                    f"  • {phone.phone_normalized} — {phone.source.value}"
                )
            lines.append("")
        return lines

    async def format_period_stats(
        self,
        start_date: date,
        end_date: date,
        title: str,
    ) -> list[str]:
        reports_result = await self.session.execute(
            select(DailyReport).where(
                DailyReport.report_date >= start_date,
                DailyReport.report_date <= end_date,
            )
        )
        reports = list(reports_result.scalars().all())
        submitted = sum(1 for report in reports if report.status == ReportStatus.SUBMITTED)
        missed = sum(1 for report in reports if report.status == ReportStatus.MISSED)
        excused = sum(1 for report in reports if report.status == ReportStatus.EXCUSED)

        phones_result = await self.session.execute(
            select(ReportPhone)
            .join(DailyReport)
            .where(
                DailyReport.report_date >= start_date,
                DailyReport.report_date <= end_date,
                DailyReport.status == ReportStatus.SUBMITTED,
            )
        )
        phones = list(phones_result.scalars().all())
        trial_count = sum(1 for phone in phones if phone.source == PhoneSource.TRIAL)
        outreach_count = sum(1 for phone in phones if phone.source == PhoneSource.OUTREACH)

        return [
            title,
            f"Период: {start_date:%d.%m.%Y} — {end_date:%d.%m.%Y}",
            f"Сдано: {submitted}",
            f"Пропущено: {missed}",
            f"Отменено: {excused}",
            f"Телефонов пробный: {trial_count}",
            f"Телефонов общение: {outreach_count}",
        ]
