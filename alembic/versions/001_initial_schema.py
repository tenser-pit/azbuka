"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-06-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

location_type = postgresql.ENUM("сад", "школа", name="location_type", create_type=False)
report_status = postgresql.ENUM("сдан", "пропущен", "отменён", name="report_status", create_type=False)
penalty_reason = postgresql.ENUM("нет_отчёта", "нет_видео", name="penalty_reason", create_type=False)


def upgrade() -> None:
    location_type.create(op.get_bind(), checkfirst=True)
    report_status.create(op.get_bind(), checkfirst=True)
    penalty_reason.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "trainers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("max_user_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("max_user_id"),
        sa.UniqueConstraint("telegram_user_id"),
    )

    op.create_table(
        "locations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("type", location_type, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("max_chat_id", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("max_chat_id"),
    )

    op.create_table(
        "pending_max_chats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("max_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("max_chat_id"),
    )

    op.create_table(
        "holiday_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cache_key", sa.String(length=20), nullable=False),
        sa.Column("data", sa.String(length=100), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cache_key"),
    )

    op.create_table(
        "trainer_assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("weekdays", postgresql.ARRAY(sa.Integer()), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trainer_id", "location_id", name="uq_trainer_location"),
    )

    op.create_table(
        "daily_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("has_video", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("status", report_status, nullable=False),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("location_id", "report_date", name="uq_location_report_date"),
    )

    op.create_table(
        "penalties",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("reason", penalty_reason, nullable=False),
        sa.Column("penalty_date", sa.Date(), nullable=False),
        sa.Column("is_removed", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_by", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "day_offs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=True),
        sa.Column("off_date", sa.Date(), nullable=False),
        sa.Column("location_ids", postgresql.ARRAY(sa.Integer()), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("day_offs")
    op.drop_table("penalties")
    op.drop_table("daily_reports")
    op.drop_table("trainer_assignments")
    op.drop_table("holiday_cache")
    op.drop_table("pending_max_chats")
    op.drop_table("locations")
    op.drop_table("trainers")
    penalty_reason.drop(op.get_bind(), checkfirst=True)
    report_status.drop(op.get_bind(), checkfirst=True)
    location_type.drop(op.get_bind(), checkfirst=True)
