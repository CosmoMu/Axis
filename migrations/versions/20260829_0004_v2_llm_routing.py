"""add v2 LLM invocation tracing and rename trade publications

Revision ID: 20260829_0004
Revises: 20260829_0003
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260829_0004"
down_revision: str | None = "20260829_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_invocations",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("source_message_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("workload", sa.String(length=32), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error_type", sa.String(length=64), nullable=True),
        sa.Column("provider_response_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "latency_ms >= 0",
            name=op.f("ck_llm_invocations_llm_invocation_latency_nonnegative"),
        ),
        sa.CheckConstraint(
            "workload IN ('SIGNAL_PARSE', 'SIGNAL_REPAIR', "
            "'ANALYSIS_PARSE', 'ANALYSIS_REWRITE')",
            name=op.f("ck_llm_invocations_llm_invocation_workload"),
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guild_config.guild_id"],
            name=op.f("fk_llm_invocations_guild_id_guild_config"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_message_id"],
            ["source_messages.id"],
            name=op.f("fk_llm_invocations_source_message_id_source_messages"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_invocations")),
    )
    op.create_index(
        "ix_llm_invocations_guild_created",
        "llm_invocations",
        ["guild_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_llm_invocations_guild_id"),
        "llm_invocations",
        ["guild_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_llm_invocations_source_message_id"),
        "llm_invocations",
        ["source_message_id"],
        unique=False,
    )

    op.add_column("trade_drafts", sa.Column("llm_invocation_id", sa.Uuid(), nullable=True))
    op.create_index(
        op.f("ix_trade_drafts_llm_invocation_id"),
        "trade_drafts",
        ["llm_invocation_id"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("fk_trade_drafts_llm_invocation_id_llm_invocations"),
        "trade_drafts",
        "llm_invocations",
        ["llm_invocation_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.rename_table("public_messages", "trade_publications")
    op.execute(
        "ALTER TABLE trade_publications "
        "RENAME CONSTRAINT pk_public_messages TO pk_trade_publications"
    )
    op.execute(
        "ALTER TABLE trade_publications "
        "RENAME CONSTRAINT public_message_per_guild TO trade_publication_per_guild"
    )
    op.execute(
        "ALTER TABLE trade_publications "
        "RENAME CONSTRAINT fk_public_messages_guild_id_guild_config "
        "TO fk_trade_publications_guild_id_guild_config"
    )
    op.execute(
        "ALTER TABLE trade_publications "
        "RENAME CONSTRAINT fk_public_messages_trade_id_trades "
        "TO fk_trade_publications_trade_id_trades"
    )
    op.execute(
        "ALTER TABLE trade_publications "
        "RENAME CONSTRAINT fk_public_messages_trade_event_id_trade_events "
        "TO fk_trade_publications_trade_event_id_trade_events"
    )
    op.execute(
        "ALTER INDEX ix_public_messages_guild_id "
        "RENAME TO ix_trade_publications_guild_id"
    )
    op.execute(
        "ALTER INDEX ix_public_messages_trade_id "
        "RENAME TO ix_trade_publications_trade_id"
    )
    op.execute(
        "ALTER INDEX ix_public_messages_trade_event_id "
        "RENAME TO ix_trade_publications_trade_event_id"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE trade_publications "
        "RENAME CONSTRAINT pk_trade_publications TO pk_public_messages"
    )
    op.execute(
        "ALTER TABLE trade_publications "
        "RENAME CONSTRAINT trade_publication_per_guild TO public_message_per_guild"
    )
    op.execute(
        "ALTER TABLE trade_publications "
        "RENAME CONSTRAINT fk_trade_publications_guild_id_guild_config "
        "TO fk_public_messages_guild_id_guild_config"
    )
    op.execute(
        "ALTER TABLE trade_publications "
        "RENAME CONSTRAINT fk_trade_publications_trade_id_trades "
        "TO fk_public_messages_trade_id_trades"
    )
    op.execute(
        "ALTER TABLE trade_publications "
        "RENAME CONSTRAINT fk_trade_publications_trade_event_id_trade_events "
        "TO fk_public_messages_trade_event_id_trade_events"
    )
    op.execute(
        "ALTER INDEX ix_trade_publications_guild_id "
        "RENAME TO ix_public_messages_guild_id"
    )
    op.execute(
        "ALTER INDEX ix_trade_publications_trade_id "
        "RENAME TO ix_public_messages_trade_id"
    )
    op.execute(
        "ALTER INDEX ix_trade_publications_trade_event_id "
        "RENAME TO ix_public_messages_trade_event_id"
    )
    op.rename_table("trade_publications", "public_messages")

    op.drop_constraint(
        op.f("fk_trade_drafts_llm_invocation_id_llm_invocations"),
        "trade_drafts",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_trade_drafts_llm_invocation_id"), table_name="trade_drafts")
    op.drop_column("trade_drafts", "llm_invocation_id")

    op.drop_index(
        op.f("ix_llm_invocations_source_message_id"),
        table_name="llm_invocations",
    )
    op.drop_index(op.f("ix_llm_invocations_guild_id"), table_name="llm_invocations")
    op.drop_index("ix_llm_invocations_guild_created", table_name="llm_invocations")
    op.drop_table("llm_invocations")
