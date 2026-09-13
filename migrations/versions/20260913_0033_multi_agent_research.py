"""add AXIS multi-agent research persistence

Revision ID: 20260913_0033
Revises: 20260910_0032
Create Date: 2026-09-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260913_0033"
down_revision: str | None = "20260910_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_runs",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("asset_type", sa.String(length=24), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("research_stance", sa.String(length=32)),
        sa.Column("research_confidence", sa.SmallInteger()),
        sa.Column("coverage_score", sa.Numeric(6, 5)),
        sa.Column("agreement_score", sa.Numeric(6, 5)),
        sa.Column("scenario_dominance", sa.Numeric(6, 5)),
        sa.Column("primary_scenario_json", sa.JSON()),
        sa.Column("levels_json", sa.JSON()),
        sa.Column("risk_json", sa.JSON()),
        sa.Column("research_pack_json", sa.JSON()),
        sa.Column("final_view_json", sa.JSON()),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("stock_analyst_version", sa.String(length=64)),
        sa.Column("gex_version", sa.String(length=64)),
        sa.Column("created_by_discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("cache_key", sa.String(length=128), nullable=False),
        sa.Column("provider_calls", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("llm_calls", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_type", sa.String(length=100)),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('RUNNING','COMPLETED','PARTIAL','INSUFFICIENT_DATA','FAILED')",
            name=op.f("ck_research_runs_research_run_status"),
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guild_config.guild_id"],
            name=op.f("fk_research_runs_guild_id_guild_config"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_runs")),
    )
    op.create_index(
        "ix_research_runs_ticker_as_of", "research_runs", ["guild_id", "ticker", "as_of"]
    )
    op.create_index(
        "ix_research_runs_cache", "research_runs", ["guild_id", "cache_key", "completed_at"]
    )
    op.create_index(op.f("ix_research_runs_guild_id"), "research_runs", ["guild_id"])
    op.create_index(op.f("ix_research_runs_ticker"), "research_runs", ["ticker"])
    op.create_index(
        op.f("ix_research_runs_created_by_discord_user_id"),
        "research_runs",
        ["created_by_discord_user_id"],
    )

    op.create_table(
        "research_agent_outputs",
        sa.Column("research_run_id", sa.Uuid(), nullable=False),
        sa.Column("agent_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("structured_output_json", sa.JSON(), nullable=False),
        sa.Column("provider", sa.String(length=32)),
        sa.Column("model", sa.String(length=100)),
        sa.Column("workload", sa.String(length=48)),
        sa.Column("prompt_version", sa.String(length=64)),
        sa.Column("schema_version", sa.String(length=64)),
        sa.Column("source_timestamp", sa.DateTime(timezone=True)),
        sa.Column("latency_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_type", sa.String(length=100)),
        sa.Column("response_id", sa.String(length=100)),
        sa.Column("input_pack_fingerprint", sa.String(length=64)),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["research_run_id"],
            ["research_runs.id"],
            name=op.f("fk_research_agent_outputs_research_run_id_research_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_agent_outputs")),
        sa.UniqueConstraint("research_run_id", "agent_type", name="research_agent_per_run"),
    )
    op.create_index(
        "ix_research_agent_run", "research_agent_outputs", ["research_run_id", "created_at"]
    )
    op.create_index(
        op.f("ix_research_agent_outputs_research_run_id"),
        "research_agent_outputs",
        ["research_run_id"],
    )

    op.create_table(
        "research_outcomes",
        sa.Column("research_run_id", sa.Uuid(), nullable=False),
        sa.Column("horizon_trading_days", sa.SmallInteger(), nullable=False),
        sa.Column("benchmark_ticker", sa.String(length=16), server_default="SPY", nullable=False),
        sa.Column("target_session_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="PENDING", nullable=False),
        sa.Column("raw_return", sa.Numeric(14, 8)),
        sa.Column("benchmark_return", sa.Numeric(14, 8)),
        sa.Column("alpha_return", sa.Numeric(14, 8)),
        sa.Column("max_favorable_excursion", sa.Numeric(14, 8)),
        sa.Column("max_adverse_excursion", sa.Numeric(14, 8)),
        sa.Column("primary_target_hit", sa.Boolean()),
        sa.Column("invalidation_hit", sa.Boolean()),
        sa.Column("resolution_timestamp", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("error_type", sa.String(length=100)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "horizon_trading_days > 0",
            name=op.f("ck_research_outcomes_research_outcome_horizon_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["research_run_id"],
            ["research_runs.id"],
            name=op.f("fk_research_outcomes_research_run_id_research_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_outcomes")),
        sa.UniqueConstraint(
            "research_run_id", "horizon_trading_days", name="research_outcome_horizon"
        ),
    )
    op.create_index(
        "ix_research_outcomes_due", "research_outcomes", ["status", "target_session_date"]
    )
    op.create_index(
        op.f("ix_research_outcomes_research_run_id"), "research_outcomes", ["research_run_id"]
    )

    op.create_table(
        "research_reflections",
        sa.Column("research_run_id", sa.Uuid(), nullable=False),
        sa.Column("research_outcome_id", sa.Uuid(), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("horizon_trading_days", sa.SmallInteger(), nullable=False),
        sa.Column("reflection_json", sa.JSON(), nullable=False),
        sa.Column("provider", sa.String(length=32)),
        sa.Column("model", sa.String(length=100)),
        sa.Column("prompt_version", sa.String(length=64)),
        sa.Column("schema_version", sa.String(length=64)),
        sa.Column("resolution_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["research_outcome_id"],
            ["research_outcomes.id"],
            name=op.f("fk_research_reflections_research_outcome_id_research_outcomes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["research_run_id"],
            ["research_runs.id"],
            name=op.f("fk_research_reflections_research_run_id_research_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_reflections")),
        sa.UniqueConstraint("research_outcome_id", name="research_reflection_per_outcome"),
    )
    op.create_index(
        "ix_research_reflections_ticker_resolved",
        "research_reflections",
        ["ticker", "resolution_timestamp"],
    )
    op.create_index(
        op.f("ix_research_reflections_research_run_id"), "research_reflections", ["research_run_id"]
    )
    op.create_index(
        op.f("ix_research_reflections_research_outcome_id"),
        "research_reflections",
        ["research_outcome_id"],
    )
    op.create_index(op.f("ix_research_reflections_ticker"), "research_reflections", ["ticker"])


def downgrade() -> None:
    op.drop_table("research_reflections")
    op.drop_table("research_outcomes")
    op.drop_table("research_agent_outputs")
    op.drop_table("research_runs")
