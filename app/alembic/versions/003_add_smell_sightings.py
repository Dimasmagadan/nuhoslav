"""add smell_sightings table

Revision ID: 003
Revises: 002
Create Date: 2026-06-26 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "smell_sightings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reported_at", sa.DateTime(), nullable=False),
        sa.Column("vessel_id", sa.Integer(), nullable=True),
        sa.Column("visit_id", sa.Integer(), nullable=True),
        sa.Column("vessel_lat", sa.Float(), nullable=True),
        sa.Column("vessel_lon", sa.Float(), nullable=True),
        sa.Column("stationary_since", sa.DateTime(), nullable=True),
        sa.Column("stationary_hours", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["vessel_id"], ["vessels.id"]),
        sa.ForeignKeyConstraint(["visit_id"], ["vessel_port_visits.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_smell_sightings_reported_at", "smell_sightings", ["reported_at"])
    op.create_index("ix_smell_sightings_vessel_id", "smell_sightings", ["vessel_id"])


def downgrade() -> None:
    op.drop_index("ix_smell_sightings_vessel_id", table_name="smell_sightings")
    op.drop_index("ix_smell_sightings_reported_at", table_name="smell_sightings")
    op.drop_table("smell_sightings")
