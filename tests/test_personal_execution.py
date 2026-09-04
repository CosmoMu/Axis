from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.config import ConfigurationError, Settings
from app.db.base import Base
from app.db.models import (
    GuildConfig,
    PersonalFill,
    PersonalOrder,
    PersonalPosition,
    SourceMessage,
    Trade,
    TradeDraft,
    TradePublication,
)
from app.db.session import Database
from app.domain.personal_execution import (
    PersonalBrokerEnvironment,
    PersonalExecutionMode,
    PersonalExecutionPolicy,
    PersonalOrderPurpose,
    PersonalRiskStage,
    evaluate_risk,
)
from app.integrations.moomoo_personal_execution import (
    BrokerAccount,
    BrokerFill,
    BrokerOrder,
)
from app.services.personal_execution import PersonalExecutionService

GUILD_ID = 1543309921066684567
OWNER_ID = 1153793989607170119


class FakeBroker:
    def __init__(self) -> None:
        self.place_calls = 0

    async def read_account(self) -> BrokerAccount:
        return BrokerAccount(
            "acct_test",
            Decimal("4000"),
            Decimal("1000"),
            Decimal("800"),
            datetime.now(UTC),
        )

    async def read_quote(self, contract_code: str):
        from app.domain.personal_execution import PersonalQuote

        return PersonalQuote(
            contract_code,
            Decimal("2.00"),
            Decimal("2.05"),
            Decimal("2.02"),
            datetime.now(UTC),
            volume=100,
            open_interest=500,
        )

    async def read_positions(self) -> tuple[object, ...]:
        return ()

    async def read_orders(self) -> tuple[BrokerOrder, ...]:
        return ()

    async def read_fills(self) -> tuple[BrokerFill, ...]:
        return ()

    async def place_limit_order(self, **kwargs: object):
        del kwargs
        self.place_calls += 1
        raise AssertionError("DRY_RUN must not write to broker")

    async def cancel_order(self, broker_order_id: str) -> None:
        del broker_order_id
        raise AssertionError("DRY_RUN must not write to broker")


def test_budget_chase_allocation_and_open_guard() -> None:
    policy = PersonalExecutionPolicy()
    assert policy.configured_budget(Decimal("1000")) == Decimal("200")
    assert policy.configured_budget(Decimal("4000")) == Decimal("400.00")
    assert policy.configured_budget(Decimal("10000")) == Decimal("500")
    assert policy.effective_budget(Decimal("10000"), Decimal("375")) == Decimal("375")
    assert policy.max_entry_price(Decimal("2")) == Decimal("2.10")
    assert policy.entry_quantity(Decimal("500"), Decimal("2.10")) == 2
    assert policy.entry_quantity(Decimal("200"), Decimal("5")) == 0
    assert policy.allocation(1) == (0, 0, 1)
    assert policy.allocation(5) == (2, 2, 1)
    assert policy.in_opening_guard(datetime(2026, 9, 3, 13, 32, tzinfo=UTC))


def test_risk_stages_tp_and_trailing_priority() -> None:
    policy = PersonalExecutionPolicy(market_open_guard_enabled=False)
    now = datetime(2026, 9, 3, 15, 0, tzinfo=UTC)
    breakeven = evaluate_risk(
        policy=policy,
        average_cost=Decimal("2"),
        current_price=Decimal("2.70"),
        current_quantity=3,
        original_quantity=3,
        prior_stage=PersonalRiskStage.INITIAL,
        prior_risk_high=Decimal("2"),
        tp50_executed=False,
        tp100_executed=False,
        observed_at=now,
    )
    assert breakeven.stage is PersonalRiskStage.BREAKEVEN
    tp50 = evaluate_risk(
        policy=policy,
        average_cost=Decimal("2"),
        current_price=Decimal("3"),
        current_quantity=5,
        original_quantity=5,
        prior_stage=PersonalRiskStage.BREAKEVEN,
        prior_risk_high=Decimal("2.70"),
        tp50_executed=False,
        tp100_executed=False,
        observed_at=now,
    )
    assert tp50.order_purpose is PersonalOrderPurpose.TP50
    assert tp50.sell_quantity == 2
    trailing = evaluate_risk(
        policy=policy,
        average_cost=Decimal("2"),
        current_price=Decimal("3"),
        current_quantity=3,
        original_quantity=5,
        prior_stage=PersonalRiskStage.TRAILING,
        prior_risk_high=Decimal("5"),
        tp50_executed=True,
        tp100_executed=False,
        observed_at=now,
    )
    assert trailing.order_purpose is PersonalOrderPurpose.TRAILING_EXIT
    assert trailing.sell_quantity == 3


@pytest.mark.asyncio
async def test_publication_dry_run_is_idempotent_and_creates_no_fake_fill() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    publication_id = uuid.uuid4()
    async with database.session() as session:
        session.add(GuildConfig(guild_id=GUILD_ID))
        source = SourceMessage(
            guild_id=GUILD_ID,
            discord_message_id=1,
            channel_id=2,
            submitted_by=OWNER_ID,
            raw_text="owner production entry",
            source_kind="SIGNAL",
            status="PARSED",
            received_at=datetime(2026, 9, 3, 15, 0, tzinfo=UTC),
        )
        session.add(source)
        await session.flush()
        draft = TradeDraft(
            guild_id=GUILD_ID,
            draft_code="S-TEST",
            source_message_id=source.id,
            status="READY",
            intent="NEW_TRADE",
            action="ENTRY",
            selected_category="SHORT_TERM",
            ticker="SPY",
            expiry=date(2026, 9, 4),
            strike=Decimal("650"),
            option_side="CALL",
            option_contract_code="O:SPY260904C00650000",
            reviewed_by=OWNER_ID,
        )
        trade = Trade(
            guild_id=GUILD_ID,
            public_trade_id="ST-TEST",
            category="SHORT_TERM",
            ticker="SPY",
            expiry=date(2026, 9, 4),
            strike=Decimal("650"),
            option_side="CALL",
            option_contract_code="O:SPY260904C00650000",
            state="DRAFT",
        )
        session.add_all([draft, trade])
        await session.flush()
        session.add(
            TradePublication(
                id=publication_id,
                guild_id=GUILD_ID,
                trade_id=trade.id,
                draft_id=draft.id,
                message_type="SIGNAL_CARD",
                channel_id=3,
                public_ref="P-TEST",
                status="PENDING",
            )
        )
        await session.commit()

    broker = FakeBroker()
    service = PersonalExecutionService(
        database,
        broker,  # type: ignore[arg-type]
        guild_id=GUILD_ID,
        owner_user_id=OWNER_ID,
        execution_mode=PersonalExecutionMode.DRY_RUN,
        broker_environment=PersonalBrokerEnvironment.SIMULATE,
        policy=PersonalExecutionPolicy(),
        production_start_date=date(2026, 8, 31),
    )
    try:
        await service.ensure_settings()
        await service.update_toggle("auto_follow_enabled", actor_user_id=OWNER_ID)
        first = await service.prepare_publication(
            publication_id,
            published_entry=Decimal("2"),
            actor_user_id=OWNER_ID,
        )
        second = await service.prepare_publication(
            publication_id,
            published_entry=Decimal("2"),
            actor_user_id=OWNER_ID,
        )
        assert first.code == "DRY_RUN_VALIDATED"
        assert second.code == "IDEMPOTENT_REUSE"
        assert first.order_id == second.order_id
        assert broker.place_calls == 0
        async with database.session() as session:
            assert await session.scalar(select(func.count()).select_from(PersonalOrder)) == 1
            assert await session.scalar(select(func.count()).select_from(PersonalPosition)) == 0
            assert await session.scalar(select(func.count()).select_from(PersonalFill)) == 0
    finally:
        await database.dispose()


def test_live_config_requires_all_explicit_safety_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DISCORD_GUILD_ID", str(GUILD_ID))
    monkeypatch.setenv("DISCORD_OWNER_USER_ID", str(OWNER_ID))
    monkeypatch.setenv("FEATURE_PERSONAL_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("PERSONAL_EXECUTION_MODE", "LIVE")
    monkeypatch.setenv("PERSONAL_AUTO_TRADING_ENABLED", "false")
    monkeypatch.setenv("PERSONAL_DRY_RUN_VALIDATED", "false")
    base: Settings = Settings.load(Path("/tmp/axis-personal-execution-test"))
    with pytest.raises(ConfigurationError, match="AUTO_TRADING"):
        base.assert_personal_execution_safety()
    with pytest.raises(ConfigurationError, match="DRY_RUN"):
        replace(base, personal_auto_trading_enabled=True).assert_personal_execution_safety()
    ready = replace(
        base,
        personal_auto_trading_enabled=True,
        personal_dry_run_validated=True,
        personal_broker_environment=PersonalBrokerEnvironment.REAL,
        personal_moomoo_account_id="test-account",
        personal_moomoo_security_firm="FUTUSECURITIES",
    )
    ready.assert_personal_execution_safety()
