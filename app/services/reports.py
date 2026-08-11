from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.db.enums import ReportStatus
from app.db.models import DailyReport, DayOff, Location, Trainer, TrainerAssignment
from app.services.holidays import HolidayService


@dataclass
class ExpectedReport:
    location: Location
    trainer: Trainer
    assignment: TrainerAssignment


class ReportService:
    def __init__(self, session: AsyncSession, settings: Settings):
        self.session = session
        self.settings = settings
        self.holiday_service = HolidayService(session)

    async def get_expected_reports(self, report_date: date) -> list[ExpectedReport]:
        if await self.holiday_service.is_holiday(report_date):
            return []

        weekday = report_date.weekday()
        day_offs = await self._get_day_offs(report_date)

        result = await self.session.execute(
            select(TrainerAssignment)
            .where(TrainerAssignment.is_active.is_(True))
            .options(
                selectinload(TrainerAssignment.trainer),
                selectinload(TrainerAssignment.location),
            )
        )
        assignments = result.scalars().all()
        expected: list[ExpectedReport] = []

        for assignment in assignments:
            location = assignment.location
            trainer = assignment.trainer

            if not trainer.is_active:
                continue
            if location.max_chat_id is None:
                continue
            if weekday not in assignment.weekdays:
                continue
            if self._is_excused(location.id, trainer.id, day_offs):
                continue

            expected.append(ExpectedReport(location=location, trainer=trainer, assignment=assignment))

        return expected

    async def get_today_status_lines(self, report_date: date) -> list[str]:
        expected = await self.get_expected_reports(report_date)
        if not expected:
            return ["Сегодня нет ожидаемых отчётов."]

        location_ids = [item.location.id for item in expected]
        reports_result = await self.session.execute(
            select(DailyReport).where(
                DailyReport.report_date == report_date,
                DailyReport.location_id.in_(location_ids),
            )
        )
        reports_by_location = {report.location_id: report for report in reports_result.scalars().all()}

        lines: list[str] = []
        for item in expected:
            report = reports_by_location.get(item.location.id)
            if report is None:
                status = "ожидается"
            else:
                status = report.status.value
            lines.append(f"{item.location.name} — {item.trainer.name}: {status}")

        return lines

    async def process_incoming_message(
        self,
        max_chat_id: int,
        sender_user_id: int,
        message_id: int,
        message_text: str,
        has_video: bool,
        report_date: date | None = None,
    ) -> bool:
        if report_date is None:
            report_date = date.today()

        if await self.holiday_service.is_holiday(report_date):
            return False

        location = await self._get_location_by_chat(max_chat_id)
        if location is None:
            return False

        if not self._contains_report_phrase(message_text):
            return False

        assignment = await self._get_assignment_for_date(location.id, report_date)
        if assignment is None:
            return False

        trainer = assignment.trainer
        if sender_user_id != trainer.max_user_id:
            return False

        day_offs = await self._get_day_offs(report_date)
        if self._is_excused(location.id, trainer.id, day_offs):
            return False

        await self._upsert_report(
            location_id=location.id,
            trainer_id=trainer.id,
            report_date=report_date,
            message_id=message_id,
            has_video=has_video,
            message_text=message_text,
        )
        return True

    async def mark_excused(
        self,
        report_date: date,
        trainer_id: int | None,
        location_ids: list[int] | None,
        created_by: int,
    ) -> list[int]:
        if trainer_id is None:
            expected = await self.get_expected_reports(report_date)
            affected_location_ids = [item.location.id for item in expected]
        elif not location_ids:
            expected = await self.get_expected_reports(report_date)
            affected_location_ids = [
                item.location.id for item in expected if item.trainer.id == trainer_id
            ]
        else:
            affected_location_ids = location_ids

        self.session.add(
            DayOff(
                trainer_id=trainer_id,
                off_date=report_date,
                location_ids=affected_location_ids or None,
                created_by=created_by,
            )
        )

        for location_id in affected_location_ids:
            assignment = await self._get_assignment_for_date(location_id, report_date)
            if assignment is None:
                continue
            if trainer_id is not None and assignment.trainer_id != trainer_id:
                continue

            existing = await self._get_report(location_id, report_date)
            if existing is None:
                self.session.add(
                    DailyReport(
                        location_id=location_id,
                        trainer_id=assignment.trainer_id,
                        report_date=report_date,
                        status=ReportStatus.EXCUSED,
                    )
                )
            else:
                existing.status = ReportStatus.EXCUSED

        await self.session.commit()
        return affected_location_ids

    def _contains_report_phrase(self, message_text: str) -> bool:
        return self.settings.report_phrase.lower() in message_text.lower()

    async def _upsert_report(
        self,
        location_id: int,
        trainer_id: int,
        report_date: date,
        message_id: int,
        has_video: bool,
        message_text: str = "",
    ) -> DailyReport:
        from app.services.phones import parse_phones_from_report_text, replace_phones_for_report

        existing = await self._get_report(location_id, report_date)
        if existing is None:
            existing = DailyReport(
                location_id=location_id,
                trainer_id=trainer_id,
                report_date=report_date,
                message_id=message_id,
                has_video=has_video,
                status=ReportStatus.SUBMITTED,
            )
            self.session.add(existing)
        else:
            existing.trainer_id = trainer_id
            existing.message_id = message_id
            existing.has_video = has_video
            existing.status = ReportStatus.SUBMITTED

        await self.session.commit()
        await self.session.refresh(existing)

        parsed_phones = parse_phones_from_report_text(message_text)
        await replace_phones_for_report(self.session, existing, parsed_phones)
        return existing

    async def _get_report(self, location_id: int, report_date: date) -> DailyReport | None:
        result = await self.session.execute(
            select(DailyReport).where(
                DailyReport.location_id == location_id,
                DailyReport.report_date == report_date,
            )
        )
        return result.scalar_one_or_none()

    async def _get_location_by_chat(self, max_chat_id: int) -> Location | None:
        result = await self.session.execute(
            select(Location).where(Location.max_chat_id == max_chat_id)
        )
        return result.scalar_one_or_none()

    async def _get_assignment_for_date(
        self, location_id: int, report_date: date
    ) -> TrainerAssignment | None:
        weekday = report_date.weekday()
        result = await self.session.execute(
            select(TrainerAssignment)
            .where(
                TrainerAssignment.location_id == location_id,
                TrainerAssignment.is_active.is_(True),
            )
            .options(selectinload(TrainerAssignment.trainer))
        )
        for assignment in result.scalars().all():
            if weekday in assignment.weekdays:
                return assignment
        return None

    async def _get_day_offs(self, report_date: date) -> list[DayOff]:
        result = await self.session.execute(select(DayOff).where(DayOff.off_date == report_date))
        return list(result.scalars().all())

    def _is_excused(self, location_id: int, trainer_id: int, day_offs: list[DayOff]) -> bool:
        for day_off in day_offs:
            if day_off.trainer_id is not None and day_off.trainer_id != trainer_id:
                continue
            if not day_off.location_ids:
                return True
            if location_id in day_off.location_ids:
                return True
        return False

    async def has_video_for_week(
        self, location_id: int, week_start: date, week_end: date
    ) -> bool:
        result = await self.session.execute(
            select(DailyReport).where(
                DailyReport.location_id == location_id,
                DailyReport.report_date >= week_start,
                DailyReport.report_date <= week_end,
                DailyReport.status == ReportStatus.SUBMITTED,
                DailyReport.has_video.is_(True),
            )
        )
        return result.scalar_one_or_none() is not None

    async def get_unique_working_locations_for_week(
        self, week_start: date, week_end: date
    ) -> list[ExpectedReport]:
        seen: set[int] = set()
        expected_all: list[ExpectedReport] = []
        current = week_start
        while current <= week_end:
            for item in await self.get_expected_reports(current):
                if item.location.id not in seen:
                    seen.add(item.location.id)
                    expected_all.append(item)
            current = date.fromordinal(current.toordinal() + 1)
        return expected_all
