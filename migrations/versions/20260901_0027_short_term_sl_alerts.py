"""add non-terminal Short-Term SL alerts and verified option contracts

Revision ID: 20260901_0027
Revises: 20260831_0026
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260901_0027"
down_revision: str | None = "20260831_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("trades", sa.Column("option_contract_code", sa.String(64)))
    op.execute(
        "UPDATE trades AS trade SET option_contract_code = draft.option_contract_code "
        "FROM trade_publications AS publication "
        "JOIN trade_drafts AS draft ON draft.id = publication.draft_id "
        "WHERE publication.trade_id = trade.id "
        "AND trade.category = 'SHORT_TERM' "
        "AND draft.contract_validation_status = 'VALID' "
        "AND draft.option_contract_code IS NOT NULL"
    )
    op.execute(
        "UPDATE short_term_tracking AS tracking "
        "SET option_ticker = trade.option_contract_code, "
        "consecutive_data_errors = 0, last_error_code = NULL "
        "FROM trades AS trade "
        "WHERE tracking.trade_id = trade.id "
        "AND trade.option_contract_code IS NOT NULL "
        "AND tracking.option_ticker <> trade.option_contract_code"
    )
    op.drop_constraint(
        "short_term_event_type",
        "short_term_tracking_events",
        type_="check",
    )
    op.create_check_constraint(
        "short_term_event_type",
        "short_term_tracking_events",
        "event_type IN ('ENTRY_PUBLISHED','FIXED_TP_HIT','FAST_MOMENTUM_REVERSAL',"
        "'SL_ALERT','TRACKING_PROTECTION_MOVED','TRACKING_STOPPED','OVERNIGHT_CARRY',"
        "'OVERNIGHT_GAP_STOP')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "short_term_event_type",
        "short_term_tracking_events",
        type_="check",
    )
    op.execute("DELETE FROM short_term_tracking_events WHERE event_type = 'SL_ALERT'")
    op.create_check_constraint(
        "short_term_event_type",
        "short_term_tracking_events",
        "event_type IN ('ENTRY_PUBLISHED','FIXED_TP_HIT','FAST_MOMENTUM_REVERSAL',"
        "'TRACKING_PROTECTION_MOVED','TRACKING_STOPPED','OVERNIGHT_CARRY',"
        "'OVERNIGHT_GAP_STOP')",
    )
    op.drop_column("trades", "option_contract_code")
