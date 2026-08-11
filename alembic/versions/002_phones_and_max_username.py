"""phones and max_username

Revision ID: 002
Revises: 001
Create Date: 2026-08-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

phone_source = postgresql.ENUM("пробный", "общение", name="phone_source", create_type=False)


def upgrade() -> None:
    phone_source.create(op.get_bind(), checkfirst=True)

    op.add_column("trainers", sa.Column("max_username", sa.String(length=100), nullable=True))

    op.create_table(
        "report_phones",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("daily_report_id", sa.Integer(), nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("phone_raw", sa.String(length=64), nullable=False),
        sa.Column("phone_normalized", sa.String(length=32), nullable=False),
        sa.Column("source", phone_source, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["daily_report_id"], ["daily_reports.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "daily_report_id",
            "phone_normalized",
            "source",
            name="uq_report_phone_source",
        ),
    )


def downgrade() -> None:
    op.drop_table("report_phones")
    op.drop_column("trainers", "max_username")
    phone_source.drop(op.get_bind(), checkfirst=True)
