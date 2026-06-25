"""initial schema

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vessels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mmsi", sa.String(length=9), nullable=False),
        sa.Column("imo", sa.String(length=10), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=True),
        sa.Column("vessel_type", sa.Integer(), nullable=True),
        sa.Column("callsign", sa.String(length=10), nullable=True),
        sa.Column("first_seen", sa.DateTime(), nullable=False),
        sa.Column("last_seen", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mmsi"),
    )

    op.create_table(
        "vessel_port_visits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vessel_id", sa.Integer(), nullable=False),
        sa.Column("entered_at", sa.DateTime(), nullable=False),
        sa.Column("left_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["vessel_id"], ["vessels.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "wind_readings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.Column("direction_deg", sa.Float(), nullable=False),
        sa.Column("speed_ms", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "smell_alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.Column("vessel_id", sa.Integer(), nullable=True),
        sa.Column("visit_id", sa.Integer(), nullable=True),
        sa.Column("wind_direction", sa.Float(), nullable=False),
        sa.Column("wind_speed", sa.Float(), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("vessel_docked_hours", sa.Float(), nullable=True),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["vessel_id"], ["vessels.id"]),
        sa.ForeignKeyConstraint(["visit_id"], ["vessel_port_visits.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "alert_feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("alert_id", sa.Integer(), nullable=False),
        sa.Column("feedback_type", sa.String(length=20), nullable=False),
        sa.Column("reported_at", sa.DateTime(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["alert_id"], ["smell_alerts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("alert_feedback")
    op.drop_table("smell_alerts")
    op.drop_table("wind_readings")
    op.drop_table("vessel_port_visits")
    op.drop_table("vessels")
