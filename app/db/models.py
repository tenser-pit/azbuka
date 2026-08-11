from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.db.enums import LocationType, PenaltyReason, PhoneSource, ReportStatus


class Base(DeclarativeBase):
    pass


class Trainer(Base):
    __tablename__ = "trainers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    max_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    max_username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    assignments: Mapped[list["TrainerAssignment"]] = relationship(back_populates="trainer")
    penalties: Mapped[list["Penalty"]] = relationship(back_populates="trainer")
    report_phones: Mapped[list["ReportPhone"]] = relationship(back_populates="trainer")


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[LocationType] = mapped_column(
        Enum(LocationType, name="location_type", values_callable=lambda enum: [item.value for item in enum]),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    max_chat_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)

    assignments: Mapped[list["TrainerAssignment"]] = relationship(back_populates="location")
    reports: Mapped[list["DailyReport"]] = relationship(back_populates="location")
    penalties: Mapped[list["Penalty"]] = relationship(back_populates="location")


class TrainerAssignment(Base):
    __tablename__ = "trainer_assignments"
    __table_args__ = (UniqueConstraint("trainer_id", "location_id", name="uq_trainer_location"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trainer_id: Mapped[int] = mapped_column(ForeignKey("trainers.id"), nullable=False)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False)
    weekdays: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    trainer: Mapped["Trainer"] = relationship(back_populates="assignments")
    location: Mapped["Location"] = relationship(back_populates="assignments")


class PendingMaxChat(Base):
    __tablename__ = "pending_max_chats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    max_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DailyReport(Base):
    __tablename__ = "daily_reports"
    __table_args__ = (UniqueConstraint("location_id", "report_date", name="uq_location_report_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False)
    trainer_id: Mapped[int] = mapped_column(ForeignKey("trainers.id"), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    has_video: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus, name="report_status", values_callable=lambda enum: [item.value for item in enum]),
        nullable=False,
    )

    location: Mapped["Location"] = relationship(back_populates="reports")
    trainer: Mapped["Trainer"] = relationship()
    phones: Mapped[list["ReportPhone"]] = relationship(
        back_populates="daily_report",
        cascade="all, delete-orphan",
    )


class ReportPhone(Base):
    __tablename__ = "report_phones"
    __table_args__ = (
        UniqueConstraint(
            "daily_report_id",
            "phone_normalized",
            "source",
            name="uq_report_phone_source",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    daily_report_id: Mapped[int] = mapped_column(ForeignKey("daily_reports.id"), nullable=False)
    trainer_id: Mapped[int] = mapped_column(ForeignKey("trainers.id"), nullable=False)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False)
    phone_raw: Mapped[str] = mapped_column(String(64), nullable=False)
    phone_normalized: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[PhoneSource] = mapped_column(
        Enum(
            PhoneSource,
            name="phone_source",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    daily_report: Mapped["DailyReport"] = relationship(back_populates="phones")
    trainer: Mapped["Trainer"] = relationship(back_populates="report_phones")
    location: Mapped["Location"] = relationship()


class Penalty(Base):
    __tablename__ = "penalties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trainer_id: Mapped[int] = mapped_column(ForeignKey("trainers.id"), nullable=False)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[PenaltyReason] = mapped_column(
        Enum(PenaltyReason, name="penalty_reason", values_callable=lambda enum: [item.value for item in enum]),
        nullable=False,
    )
    penalty_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_removed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    removed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    trainer: Mapped["Trainer"] = relationship(back_populates="penalties")
    location: Mapped["Location"] = relationship(back_populates="penalties")


class DayOff(Base):
    __tablename__ = "day_offs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trainer_id: Mapped[int | None] = mapped_column(ForeignKey("trainers.id"), nullable=True)
    off_date: Mapped[date] = mapped_column(Date, nullable=False)
    location_ids: Mapped[list[int] | None] = mapped_column(ARRAY(Integer), nullable=True)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    trainer: Mapped["Trainer | None"] = relationship()


class HolidayCache(Base):
    __tablename__ = "holiday_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cache_key: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    data: Mapped[str] = mapped_column(String(100), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
