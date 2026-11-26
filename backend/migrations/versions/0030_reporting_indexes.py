"""Reporting indexes: stored conversions by time, link-tagged events by receipt

Revision ID: 0030_reporting_indexes
Revises: 0029_attribution_persistence
Created: 2026-11-26

Specification 016-B (D-089, decision D12; specs/016-analytics-reporting/design-016b.md section
10). Adds two indexes and nothing else: attribution_conversions (client_id, effective_at, id)
for the person-level conversions list, which pages in conversion-time order, and the partial
collected_events (client_id, first_received_at) WHERE link_id IS NOT NULL for the funnel's
tracked visits. No table, column, grant or data policy row changes. The downgrade drops both
indexes; it loses no data and needs no empty-state check.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030_reporting_indexes"
down_revision: str | Sequence[str] | None = "0029_attribution_persistence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONVERSIONS_INDEX = "ix_attribution_conversions_client_effective"
EVENTS_INDEX = "ix_collected_events_client_link_received"


def upgrade() -> None:
    op.create_index(
        CONVERSIONS_INDEX, "attribution_conversions", ["client_id", "effective_at", "id"]
    )
    op.create_index(
        EVENTS_INDEX,
        "collected_events",
        ["client_id", "first_received_at"],
        postgresql_where=sa.text("link_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(EVENTS_INDEX, table_name="collected_events")
    op.drop_index(CONVERSIONS_INDEX, table_name="attribution_conversions")
