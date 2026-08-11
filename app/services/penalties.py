from datetime import date, datetime, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.db.enums import PenaltyReason, ReportStatus
from app.db.models import DailyReport, Penalty, Trainer
from app.services.reports import ReportService


class PenaltyService:
    def __init__(self, session: AsyncSession, settings: Settings):
        self.session = session
        self.settings = settings
        self.report_service = ReportService(session, settings)

    async def apply_daily_penalties(self, penalty_date: date) -> list[Penalty]:
        expected = await self.report_service.get_expected_reports(penalty_date)
        created: list[Penalty] = []

        location_ids = [item.location.id for item in expected]
        reports_result = await self.session.execute(
            select(DailyReport).where(
                DailyReport.report_date == penalty_date,
                DailyReport.location_id.in_(location_ids),
            )
        )
        reports_by_location = {report.location_id: report for report in reports_result.scalars().all()}

        for item in expected:
            report = reports_by_location.get(item.location.id)
            if report is not None and report.status == ReportStatus.SUBMITTED:
                continue
            if report is not None and report.status == ReportStatus.EXCUSED:
                continue

            penalty = await self._create_penalty_if_missing(
                trainer_id=item.trainer.id,
                location_id=item.location.id,
                penalty_date=penalty_date,
                reason=PenaltyReason.MISSED_REPORT,
            )
            if penalty is not None:
                created.append(penalty)

            if report is None:
                self.session.add(
                    DailyReport(
                        location_id=item.location.id,
                        trainer_id=item.trainer.id,
                        report_date=penalty_date,
                        status=ReportStatus.MISSED,
                    )
                )
            elif report.status != ReportStatus.SUBMITTED:
                report.status = ReportStatus.MISSED

        await self.session.commit()
        return created

    async def apply_video_penalties(self, check_date: date) -> list[Penalty]:
        week_start = check_date.fromordinal(check_date.toordinal() - check_date.weekday())
        week_end = week_start.fromordinal(week_start.toordinal() + 4)

        working_locations = await self.report_service.get_unique_working_locations_for_week(
            week_start, week_end
        )
        created: list[Penalty] = []

        for item in working_locations:
            has_video = await self.report_service.has_video_for_week(
                item.location.id, week_start, week_end
            )
            if has_video:
                continue

            penalty = await self._create_penalty_if_missing(
                trainer_id=item.trainer.id,
                location_id=item.location.id,
                penalty_date=check_date,
                reason=PenaltyReason.MISSED_VIDEO,
            )
            if penalty is not None:
                created.append(penalty)

        await self.session.commit()
        return created

    async def remove_penalty(self, penalty_id: int, removed_by: int) -> Penalty | None:
        result = await self.session.execute(select(Penalty).where(Penalty.id == penalty_id))
        penalty = result.scalar_one_or_none()
        if penalty is None or penalty.is_removed:
            return None

        penalty.is_removed = True
        penalty.removed_at = datetime.now(timezone.utc)
        penalty.removed_by = removed_by
        await self.session.commit()
        return penalty

    async def get_active_penalties(self) -> list[Penalty]:
        result = await self.session.execute(
            select(Penalty)
            .where(Penalty.is_removed.is_(False))
            .options(selectinload(Penalty.trainer), selectinload(Penalty.location))
            .order_by(Penalty.penalty_date.desc())
        )
        return list(result.scalars().all())

    async def get_summary(
        self, start_date: date, end_date: date
    ) -> list[tuple[Trainer, int, int]]:
        result = await self.session.execute(
            select(
                Trainer,
                func.count(Penalty.id),
                func.coalesce(func.sum(Penalty.amount), 0),
            )
            .join(Penalty, Penalty.trainer_id == Trainer.id)
            .where(
                Penalty.is_removed.is_(False),
                Penalty.penalty_date >= start_date,
                Penalty.penalty_date <= end_date,
            )
            .group_by(Trainer.id)
        )
        return [(row[0], int(row[1]), int(row[2])) for row in result.all()]

    async def get_month_stats(self, year: int, month: int) -> dict[str, int | float]:
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1).fromordinal(date(year + 1, 1, 1).toordinal() - 1)
        else:
            end_date = date(year, month + 1, 1).fromordinal(date(year, month + 1, 1).toordinal() - 1)

        penalties_result = await self.session.execute(
            select(func.count(Penalty.id), func.coalesce(func.sum(Penalty.amount), 0)).where(
                Penalty.is_removed.is_(False),
                Penalty.penalty_date >= start_date,
                Penalty.penalty_date <= end_date,
            )
        )
        penalty_count, penalty_sum = penalties_result.one()

        reports_result = await self.session.execute(
            select(DailyReport.status, func.count(DailyReport.id))
            .where(DailyReport.report_date >= start_date, DailyReport.report_date <= end_date)
            .group_by(DailyReport.status)
        )
        report_counts = {status.value: count for status, count in reports_result.all()}
        submitted = report_counts.get(ReportStatus.SUBMITTED.value, 0)
        missed = report_counts.get(ReportStatus.MISSED.value, 0)
        excused = report_counts.get(ReportStatus.EXCUSED.value, 0)
        total = submitted + missed + excused
        submit_rate = round(submitted / total * 100, 1) if total else 0.0

        return {
            "penalty_count": int(penalty_count),
            "penalty_sum": int(penalty_sum),
            "submitted": submitted,
            "missed": missed,
            "excused": excused,
            "submit_rate": submit_rate,
        }

    async def _create_penalty_if_missing(
        self,
        trainer_id: int,
        location_id: int,
        penalty_date: date,
        reason: PenaltyReason,
    ) -> Penalty | None:
        result = await self.session.execute(
            select(Penalty).where(
                Penalty.trainer_id == trainer_id,
                Penalty.location_id == location_id,
                Penalty.penalty_date == penalty_date,
                Penalty.reason == reason,
                Penalty.is_removed.is_(False),
            )
        )
        if result.scalar_one_or_none() is not None:
            return None

        penalty = Penalty(
            trainer_id=trainer_id,
            location_id=location_id,
            amount=-self.settings.fine_amount,
            reason=reason,
            penalty_date=penalty_date,
        )
        self.session.add(penalty)
        return penalty
