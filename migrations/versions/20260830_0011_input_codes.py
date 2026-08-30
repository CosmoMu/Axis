"""add short sequential manager-facing input codes

Revision ID: 20260830_0011
Revises: 20260830_0010
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0011"
down_revision: str | None = "20260830_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "input_code_counters",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("input_kind", sa.String(length=16), nullable=False),
        sa.Column("next_value", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "input_kind IN ('SIGNAL','ANALYSIS')",
            name=op.f("ck_input_code_counters_input_code_kind"),
        ),
        sa.CheckConstraint(
            "next_value >= 1",
            name=op.f("ck_input_code_counters_input_code_next_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guild_config.guild_id"],
            name=op.f("fk_input_code_counters_guild_id_guild_config"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "guild_id",
            "input_kind",
            name=op.f("pk_input_code_counters"),
        ),
    )
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY guild_id ORDER BY created_at, id
                       ) AS sequence_number
                FROM trade_drafts
            )
            UPDATE trade_drafts AS draft
            SET draft_code = 'S-' || LPAD(ranked.sequence_number::text, 5, '0')
            FROM ranked
            WHERE draft.id = ranked.id
            """
        )
    )
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY guild_id ORDER BY created_at, id
                       ) AS sequence_number
                FROM analysis_drafts
            )
            UPDATE analysis_drafts AS draft
            SET draft_code = 'A-' || LPAD(ranked.sequence_number::text, 5, '0')
            FROM ranked
            WHERE draft.id = ranked.id
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO input_code_counters (guild_id, input_kind, next_value)
            SELECT guild.guild_id, kind.input_kind,
                   CASE kind.input_kind
                       WHEN 'SIGNAL' THEN (SELECT COUNT(*) + 1 FROM trade_drafts
                                           WHERE trade_drafts.guild_id = guild.guild_id)
                       ELSE (SELECT COUNT(*) + 1 FROM analysis_drafts
                             WHERE analysis_drafts.guild_id = guild.guild_id)
                   END
            FROM guild_config AS guild
            CROSS JOIN (VALUES ('SIGNAL'), ('ANALYSIS')) AS kind(input_kind)
            """
        )
    )


def downgrade() -> None:
    op.drop_table("input_code_counters")
