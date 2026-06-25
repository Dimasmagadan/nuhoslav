"""add indexes on hot filter and FK columns

Revision ID: 002
Revises: 001
Create Date: 2026-06-25 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_vessel_port_visits_left_at", "vessel_port_visits", ["left_at"])
    op.create_index("ix_smell_alerts_sent_at", "smell_alerts", ["sent_at"])
    op.create_index("ix_smell_alerts_vessel_id", "smell_alerts", ["vessel_id"])
    op.create_index("ix_alert_feedback_alert_id", "alert_feedback", ["alert_id"])


def downgrade() -> None:
    op.drop_index("ix_alert_feedback_alert_id", table_name="alert_feedback")
    op.drop_index("ix_smell_alerts_vessel_id", table_name="smell_alerts")
    op.drop_index("ix_smell_alerts_sent_at", table_name="smell_alerts")
    op.drop_index("ix_vessel_port_visits_left_at", table_name="vessel_port_visits")
