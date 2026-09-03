from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.base import Base
from app.db.bootstrap import seed_guild_config
from app.db.models import GuildConfig, Mentor, Trade
from app.db.session import Database
from app.domain.enums import OptionSide, TradeCategory, TradeState

EXPECTED_TABLES = {
    "swing_tracking",
    "swing_tracking_events",
    "swing_daily_snapshots",
    "access_applications",
    "analysis_draft_revisions",
    "analysis_drafts",
    "analysis_key_levels",
    "analysis_indicators",
    "analysis_points",
    "analysis_prediction_points",
    "analysis_publications",
    "analysis_scenarios",
    "analysis_symbols",
    "daily_summary_publications",
    "daily_results_publications",
    "daily_results_reviews",
    "daily_results_items",
    "guild_config",
    "input_code_counters",
    "mentors",
    "mentor_aliases",
    "source_messages",
    "source_attachments",
    "trade_drafts",
    "trades",
    "trade_events",
    "trade_publications",
    "llm_invocations",
    "memberships",
    "membership_sessions",
    "market_quote_snapshots",
    "mentor_analyses",
    "membership_events",
    "membership_prices",
    "membership_acknowledgements",
    "membership_entitlements",
    "membership_trials",
    "newcomer_profiles",
    "newcomer_risk_flags",
    "payment_events",
    "subscriptions",
    "payment_webhook_events",
    "system_alerts",
    "short_term_tracking",
    "short_term_tracking_events",
    "short_term_daily_snapshots",
    "audit_logs",
    "scheduled_jobs",
}


def discord_ids() -> dict[str, object]:
    return {
        "guild_id": 1543309921066684567,
        "roles": {"manager": 101, "member": 102, "newcomer": 103},
        "channels": {
            "official_results": 201,
            "short_term_alerts": 202,
            "swing_alerts": 203,
            "leaps_alerts": 204,
            "mentor_control": 205,
            "member_control": 206,
            "results_review": 207,
            "join_review": 208,
        },
    }


def test_metadata_contains_the_complete_mvp_schema() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES
    trades = Base.metadata.tables["trades"]
    drafts = Base.metadata.tables["trade_drafts"]
    assert {"position_eighths", "max_position_eighths", "version"} <= set(trades.columns.keys())
    assert {
        "result_message_id",
        "final_return_pct",
        "result_published_at",
    } <= set(trades.columns.keys())
    assert "mentor_panel_message_id" in Base.metadata.tables["guild_config"].columns
    assert "member_panel_message_id" in Base.metadata.tables["guild_config"].columns
    assert "member_lounge_channel_id" in Base.metadata.tables["guild_config"].columns
    assert {
        "welcome_message_id",
        "subscription_message_id",
        "system_alerts_channel_id",
        "card_testing_channel_id",
        "results_review_channel_id",
        "join_review_channel_id",
        "newcomer_role_id",
        "newcomer_status_message_id",
        "newcomer_gate_activated_at",
    } <= set(Base.metadata.tables["guild_config"].columns.keys())
    memberships = Base.metadata.tables["memberships"]
    assert {
        "discord_user_id",
        "provider",
        "provider_customer_id",
        "provider_subscription_id",
    } <= set(memberships.columns.keys())
    assert "environment" in Base.metadata.tables["membership_prices"].columns
    assert "payment_environment" in Base.metadata.tables["membership_entitlements"].columns
    assert "payment_environment" in Base.metadata.tables["membership_sessions"].columns
    assert "environment" in Base.metadata.tables["payment_events"].columns
    trials = Base.metadata.tables["membership_trials"]
    assert {
        "duration_unit",
        "duration_amount",
        "calendar_days_granted",
        "trading_days_granted",
        "started_at",
        "expires_at",
        "updated_at",
        "application_id",
        "approved_by_user_id",
    } <= set(trials.columns.keys())
    applications = Base.metadata.tables["access_applications"]
    assert {
        "discord_user_id",
        "discovery_source",
        "referred_by_text",
        "interests",
        "risk_acknowledged",
        "community_rules_acknowledged",
        "status",
        "reviewed_by_user_id",
    } <= set(applications.columns.keys())
    assert {"risk_code", "severity", "occurrence_count", "resolved_at"} <= set(
        Base.metadata.tables["newcomer_risk_flags"].columns.keys()
    )
    assert trials.c.first_trading_day.nullable
    assert trials.c.last_trading_day.nullable
    assert "source_kind" in Base.metadata.tables["source_messages"].columns
    assert "moomoo_option_code" in Base.metadata.tables["trades"].columns
    for column in (
        "expiry_input",
        "expiry_precision",
        "expiry_resolution_status",
        "option_contract_code",
        "contract_validation_status",
        "price_parse_confidence",
    ):
        assert column in Base.metadata.tables["trade_drafts"].columns
    assert {"review_channel_id", "review_message_id"} <= set(drafts.columns.keys())
    assert "llm_invocation_id" in drafts.columns
    events = Base.metadata.tables["trade_events"]
    publications = Base.metadata.tables["trade_publications"]
    assert "draft_id" in events.columns
    assert {
        "draft_id",
        "public_ref",
        "status",
        "attempt_count",
        "claim_token",
        "claimed_at",
        "last_error_code",
        "published_at",
    } <= set(publications.columns.keys())
    invocations = Base.metadata.tables["llm_invocations"]
    assert {
        "provider",
        "model",
        "workload",
        "prompt_version",
        "schema_version",
        "latency_ms",
        "success",
        "error_type",
    } <= set(invocations.columns.keys())


@pytest.mark.asyncio
async def test_database_seed_is_idempotent_and_position_constraint_is_enforced() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    try:
        async with database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with database.session() as session:
            first = await seed_guild_config(
                session,
                guild_id=1543309921066684567,
                discord_ids=discord_ids(),
            )
            second = await seed_guild_config(
                session,
                guild_id=1543309921066684567,
                discord_ids=discord_ids(),
            )
            assert first is second
            await session.commit()

        async with database.session() as session:
            config = await session.get(GuildConfig, 1543309921066684567)
            assert config is not None
            assert config.short_term_channel_id == 202
            mentor = Mentor(
                guild_id=config.guild_id,
                name="Test Mentor",
                short_code="TEST",
            )
            session.add(mentor)
            await session.flush()
            session.add(
                Trade(
                    guild_id=config.guild_id,
                    public_trade_id="ST-0001",
                    category=TradeCategory.SHORT_TERM.value,
                    mentor_id=mentor.id,
                    ticker="AXIS",
                    expiry=date(2027, 1, 15),
                    strike=Decimal("100"),
                    option_side=OptionSide.CALL.value,
                    state=TradeState.ACTIVE.value,
                    position_eighths=1,
                    max_position_eighths=1,
                    opened_at=datetime.now(UTC),
                )
            )
            await session.commit()

        async with database.session() as session:
            mentor = Mentor(
                guild_id=1543309921066684567,
                name="Invalid Position Mentor",
                short_code="BADPOS",
            )
            session.add(mentor)
            await session.flush()
            session.add(
                Trade(
                    guild_id=1543309921066684567,
                    public_trade_id="ST-0002",
                    category=TradeCategory.SHORT_TERM.value,
                    mentor_id=mentor.id,
                    ticker="AXIS",
                    expiry=date(2027, 1, 15),
                    strike=Decimal("100"),
                    option_side=OptionSide.CALL.value,
                    state=TradeState.ACTIVE.value,
                    position_eighths=9,
                    max_position_eighths=9,
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
    finally:
        await database.dispose()
