from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db.base import Base
from app.db.models import (
    DailySummaryPublication,
    GuildConfig,
    ShortTermTracking,
    ShortTermTrackingEvent,
    Trade,
)
from app.db.session import Database
from app.integrations.massive_market_data import MarketPrice
from app.services.daily_summary import DailySummaryService
from app.services.short_term_policy import ShortTermTrackingPolicy
from app.services.short_term_tracking import MarketTrackingService

GUILD_ID = 1543309921066684567
POLICY_PATH = Path(__file__).resolve().parents[1] / "config" / "short_term_tracking.yaml"
V2_POLICY_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "short_term_tracking_v2.yaml"
)
V3_POLICY_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "short_term_tracking_v3.yaml"
)


async def tracking_database() -> tuple[Database, Trade]:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with database.session() as session:
        session.add(
            GuildConfig(
                guild_id=GUILD_ID,
                results_channel_id=101,
                short_term_channel_id=102,
                swing_channel_id=103,
                leaps_channel_id=104,
            )
        )
        trade = Trade(
            guild_id=GUILD_ID,
            public_trade_id="ST-0001",
            category="SHORT_TERM",
            mentor_id=None,
            ticker="NVDA",
            expiry=date(2027, 1, 15),
            strike=Decimal("500"),
            option_side="CALL",
            state="ACTIVE",
            position_eighths=0,
            max_position_eighths=0,
        )
        session.add(trade)
        await session.commit()
    return database, trade


def market_price(
    tracking_id,
    price: str,
    at: datetime,
    *,
    received_at: datetime | None = None,
) -> MarketPrice:
    return MarketPrice(
        key=str(tracking_id),
        option_ticker="O:NVDA270115C00500000",
        price=Decimal(price),
        price_source="MID",
        source_timestamp=at,
        received_at=received_at or at,
        market_status="open",
    )


async def registered_service(
    policy_path: Path = POLICY_PATH,
) -> tuple[Database, MarketTrackingService, ShortTermTracking]:
    database, trade = await tracking_database()
    service = MarketTrackingService(
        database,
        ShortTermTrackingPolicy.load(policy_path),
        None,
    )
    await service.register_trade(trade.id, Decimal("1.00"))
    async with database.session() as session:
        tracking = await session.scalar(select(ShortTermTracking))
    assert tracking is not None
    return database, service, tracking


@pytest.mark.asyncio
async def test_all_fixed_tp_levels_fire_once_and_watermarks_are_saved() -> None:
    database, service, tracking = await registered_service()
    now = datetime.now(UTC)
    try:
        await service.expire_contracts(GUILD_ID)
        await service.process_price(tracking.id, market_price(tracking.id, "11.00", now))
        await service.process_price(
            tracking.id, market_price(tracking.id, "11.50", now + timedelta(seconds=5))
        )
        async with database.session() as session:
            saved = await session.get(ShortTermTracking, tracking.id)
            events = list(
                await session.scalars(
                    select(ShortTermTrackingEvent).where(
                        ShortTermTrackingEvent.tp_return_pct.is_not(None)
                    )
                )
            )
            events.sort(key=lambda event: event.tp_return_pct or 0)
        assert saved is not None
        assert saved.tp_levels_hit == [f"TP{index}" for index in range(1, 42)]
        assert saved.tracking_policy_version == "ST_TRACKING_V4"
        assert saved.highest_price == Decimal("11.5000")
        assert saved.highest_return_pct == Decimal("1050.0000")
        assert len(events) == 41
        assert len({event.tp_return_pct for event in events}) == 41
        assert {event.public_card_type for event in events} == {
            f"TP{index}" for index in range(1, 42)
        }
        assert all(event.event_type == "FIXED_TP_HIT" for event in events)
        assert [(event.public_price, event.public_return_pct) for event in events] == [
            (Decimal("1") + Decimal(return_pct) / 100, Decimal(return_pct))
            for return_pct in [10, 20, *range(50, 1001, 25)]
        ]
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_high_low_and_tracking_protection_stop_are_internal_states() -> None:
    database, service, tracking = await registered_service()
    now = datetime.now(UTC)
    try:
        await service.process_price(tracking.id, market_price(tracking.id, "2.00", now))
        await service.process_price(
            tracking.id, market_price(tracking.id, "1.50", now + timedelta(seconds=10))
        )
        async with database.session() as session:
            saved = await session.get(ShortTermTracking, tracking.id)
            stop = await session.scalar(
                select(ShortTermTrackingEvent).where(
                    ShortTermTrackingEvent.event_type == "TRACKING_STOPPED"
                )
            )
        assert saved is not None and stop is not None
        assert saved.tracking_protection_price == Decimal("1.7500")
        assert saved.tracking_protection_return_pct == Decimal("75.0000")
        assert saved.tracking_state == "STOPPED"
        assert saved.tracking_end_reason == "TRAILING_TRACKING_PROTECTION"
        assert saved.highest_return_pct == Decimal("100.0000")
        assert saved.lowest_return_pct == Decimal("0.0000")
        assert stop.public_card_type == "STOP_TRACKING"
        assert stop.event_type not in {"CLOSE", "SL", "SELL"}
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_tp10_and_tp20_keep_protection_at_entry() -> None:
    database, service, tracking = await registered_service()
    now = datetime.now(UTC)
    try:
        await service.process_price(tracking.id, market_price(tracking.id, "1.20", now))
        await service.process_price(
            tracking.id, market_price(tracking.id, "1.00", now + timedelta(seconds=10))
        )
        async with database.session() as session:
            saved = await session.get(ShortTermTracking, tracking.id)
            stop = await session.scalar(
                select(ShortTermTrackingEvent).where(
                    ShortTermTrackingEvent.event_type == "TRACKING_STOPPED"
                )
            )
        assert saved is not None and stop is not None
        assert saved.tp_levels_hit == ["TP1", "TP2"]
        assert saved.tracking_protection_price == Decimal("1.0000")
        assert saved.tracking_protection_return_pct == Decimal("0.0000")
        assert saved.tracking_protection_reason == "TP2_ENTRY_PROTECTION"
        assert saved.tracking_state == "STOPPED"
        assert stop.public_notification is True
        assert stop.public_card_type == "STOP_TRACKING"
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_fast_momentum_cooldown_and_new_high_rearm() -> None:
    database, service, tracking = await registered_service()
    now = datetime.now(UTC)
    try:
        await service.process_price(tracking.id, market_price(tracking.id, "2.00", now))
        await service.process_price(
            tracking.id, market_price(tracking.id, "1.79", now + timedelta(seconds=30))
        )
        await service.process_price(
            tracking.id, market_price(tracking.id, "1.76", now + timedelta(minutes=16))
        )
        await service.process_price(
            tracking.id, market_price(tracking.id, "2.20", now + timedelta(minutes=17))
        )
        await service.process_price(
            tracking.id,
            market_price(tracking.id, "1.95", now + timedelta(minutes=17, seconds=30)),
        )
        async with database.session() as session:
            events = list(
                await session.scalars(
                    select(ShortTermTrackingEvent).where(
                        ShortTermTrackingEvent.event_type == "FAST_MOMENTUM_REVERSAL"
                    )
                )
            )
        assert len(events) == 2
        assert events[0].high_watermark_price == Decimal("2.0000")
        assert events[0].trigger_market_price == Decimal("1.7900")
        assert events[0].public_price == Decimal("2.0000")
        assert events[0].trigger_market_price != events[0].public_price
        assert {event.public_card_type for event in events} == {"TP"}
        async with database.session() as session:
            saved = await session.get(ShortTermTracking, tracking.id)
        assert saved is not None
        assert saved.tp_levels_hit == ["TP1", "TP2", "TP3", "TP4", "TP5"]
    finally:
        await database.dispose()


@pytest.mark.parametrize(
    ("historical_path", "quote", "expected_returns"),
    [
        (V2_POLICY_PATH, "1.50", [20, 50]),
        (V3_POLICY_PATH, "1.70", [10, 20, 50, 70]),
    ],
)
@pytest.mark.asyncio
async def test_existing_tracking_keeps_its_frozen_tp_policy(
    historical_path: Path,
    quote: str,
    expected_returns: list[int],
) -> None:
    database, _historical_service, tracking = await registered_service(historical_path)
    v2_policy = ShortTermTrackingPolicy.load(V2_POLICY_PATH)
    v3_policy = ShortTermTrackingPolicy.load(V3_POLICY_PATH)
    service = MarketTrackingService(
        database,
        ShortTermTrackingPolicy.load(POLICY_PATH),
        None,
        historical_policies=(v2_policy, v3_policy),
    )
    now = datetime.now(UTC)
    try:
        await service.process_price(tracking.id, market_price(tracking.id, quote, now))
        async with database.session() as session:
            saved = await session.get(ShortTermTracking, tracking.id)
            events = list(
                await session.scalars(
                    select(ShortTermTrackingEvent).where(
                        ShortTermTrackingEvent.tp_return_pct.is_not(None)
                    )
                )
            )
            events.sort(key=lambda event: event.tp_return_pct or 0)
        assert saved is not None
        assert saved.tracking_policy_version == ShortTermTrackingPolicy.load(
            historical_path
        ).version
        assert saved.tp_levels_hit == [
            f"TP{index}" for index in range(1, len(expected_returns) + 1)
        ]
        assert [event.tp_return_pct for event in events] == expected_returns
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_slow_pullback_does_not_trigger_momentum() -> None:
    database, service, tracking = await registered_service()
    now = datetime.now(UTC)
    try:
        await service.process_price(tracking.id, market_price(tracking.id, "2.36", now))
        await service.process_price(
            tracking.id, market_price(tracking.id, "2.10", now + timedelta(minutes=20))
        )
        async with database.session() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(ShortTermTrackingEvent)
                .where(ShortTermTrackingEvent.event_type == "FAST_MOMENTUM_REVERSAL")
            )
        assert count == 0
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_overnight_gap_publishes_stop_and_enters_next_daily_results() -> None:
    database, service, tracking = await registered_service()
    first_day = datetime(2026, 8, 28, 19, 0, tzinfo=UTC)
    try:
        await service.process_price(tracking.id, market_price(tracking.id, "2.00", first_day))
        summaries = DailySummaryService(database)
        session_date = date(2026, 8, 28)
        await summaries.prepare_session(GUILD_ID, session_date)
        async with database.session() as session:
            overnight = await session.get(ShortTermTracking, tracking.id)
            summary_categories = set(
                await session.scalars(select(DailySummaryPublication.category))
            )
        assert overnight is not None
        assert overnight.tracking_state == "OVERNIGHT_ACTIVE"
        assert overnight.overnight_count == 1
        assert summary_categories == {"SWING", "LEAPS"}

        second_day = first_day + timedelta(days=3)
        await service.process_price(tracking.id, market_price(tracking.id, "1.40", second_day))
        next_session = session_date + timedelta(days=3)
        await summaries.prepare_session(GUILD_ID, next_session)
        claim = await summaries.next_results_publishable(GUILD_ID, next_session)
        async with database.session() as session:
            stopped = await session.get(ShortTermTracking, tracking.id)
            gap_event = await session.scalar(
                select(ShortTermTrackingEvent).where(
                    ShortTermTrackingEvent.event_type == "OVERNIGHT_GAP_STOP"
                )
            )
        assert stopped is not None and gap_event is not None and claim is not None
        assert stopped.tracking_end_reason == "OVERNIGHT_GAP_TRACKING_PROTECTION"
        assert gap_event.public_notification is True
        assert len(claim.card.short_term) == 1
        assert claim.card.short_term[0].tracking_end_return_pct == Decimal("40.0000")
        assert claim.card.short_term[0].maximum_return_pct == Decimal("100.0000")
        assert claim.card.short_term[0].displayed_result_pct == Decimal("100.0000")
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_daily_result_uses_tracking_end_when_no_tp_was_triggered() -> None:
    database, service, tracking = await registered_service()
    at = datetime(2026, 8, 28, 18, 0, tzinfo=UTC)
    try:
        await service.process_price(tracking.id, market_price(tracking.id, "0.49", at))
        summaries = DailySummaryService(database)
        await summaries.prepare_session(GUILD_ID, date(2026, 8, 28))
        claim = await summaries.next_results_publishable(GUILD_ID, date(2026, 8, 28))
        assert claim is not None
        assert len(claim.card.short_term) == 1
        row = claim.card.short_term[0]
        assert row.tracking_end_return_pct == Decimal("-51.0000")
        assert row.maximum_return_pct == Decimal("0.0000")
        assert row.displayed_result_pct == Decimal("-51.0000")
    finally:
        await database.dispose()
