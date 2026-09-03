from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app.bot.cards import build_swing_active_embed, build_swing_tracking_embed
from app.db.base import Base
from app.db.models import (
    GuildConfig,
    SourceMessage,
    SwingDailySnapshot,
    SwingTracking,
    SwingTrackingEvent,
    Trade,
    TradeDraft,
)
from app.db.session import Database
from app.domain.enums import DraftStatus, SourceStatus
from app.domain.public_cards import (
    SwingActivePosition,
    SwingTrackedEntryCard,
    SwingTrackingCard,
)
from app.integrations.massive_market_data import MarketPrice
from app.services.option_contracts import parse_swing_close
from app.services.short_term_policy import ShortTermTrackingPolicy
from app.services.swing_tracking import (
    SIMPLE_TRACKED_SWING,
    SwingTrackingError,
    SwingTrackingService,
)
from app.services.trade_publication import TradePublicationService

GUILD_ID = 1543309921066684567
POLICY_PATH = Path(__file__).resolve().parents[1] / "config" / "short_term_tracking.yaml"


async def swing_database(*, mode: str = SIMPLE_TRACKED_SWING) -> tuple[Database, Trade]:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with database.session() as session:
        session.add(GuildConfig(guild_id=GUILD_ID, swing_channel_id=103))
        trade = Trade(
            guild_id=GUILD_ID,
            public_trade_id="SW-0001",
            category="SWING",
            tracking_mode=mode,
            mentor_id=None,
            ticker="TSLA",
            expiry=date.today() + timedelta(days=30),
            strike=Decimal("400"),
            option_side="CALL",
            option_contract_code="O:TSLA261016C00400000",
            state="ACTIVE",
            position_eighths=0,
            max_position_eighths=0,
        )
        session.add(trade)
        await session.commit()
    return database, trade


def quote(tracking: SwingTracking, value: str, at: datetime) -> MarketPrice:
    return MarketPrice(
        key=str(tracking.id),
        option_ticker=tracking.option_ticker,
        price=Decimal(value),
        price_source="MID",
        source_timestamp=at,
        received_at=at,
        market_status="open",
    )


def test_manual_swing_close_parser_supports_public_id_and_contract() -> None:
    by_id = parse_swing_close("close SW-0001 @5.20")
    assert by_id is not None
    assert by_id.public_trade_id == "SW-0001"
    assert by_id.reference_price == Decimal("5.20")

    by_contract = parse_swing_close("平仓 TSLA 10/16 400C")
    assert by_contract is not None
    assert by_contract.ticker == "TSLA"
    assert by_contract.expiry_input == "10/16"
    assert by_contract.strike == Decimal("400")
    assert by_contract.option_side == "CALL"
    assert by_contract.reference_price is None


def test_swing_active_view_uses_compact_member_format() -> None:
    embed = build_swing_active_embed(
        (
            SwingActivePosition(
                public_trade_id="SW-TEST1",
                ticker="TSLA",
                expiry=date(2026, 10, 16),
                strike=Decimal("400"),
                option_side="CALL",
                entry_price=Decimal("3.25"),
                highest_tp_level="TP5",
                highest_tp_return_pct=100,
                highest_price=Decimal("6.89"),
                highest_return_pct=Decimal("112"),
                current_price=Decimal("5.20"),
                current_return_pct=Decimal("60"),
                last_quote_at=datetime(2026, 9, 3, 23, 13, tzinfo=UTC),
                stale=False,
            ),
        )
    )
    payload = embed.to_dict()
    assert payload["title"] == "当前 Swing 订单"
    assert payload["fields"][0]["name"] == "SW-TEST1"
    assert payload["fields"][0]["value"] == (
        "TSLA 10/16 400C\n"
        "成本 $3.25\n"
        "最高 TP TP5 · +100%\n"
        "当前 $5.2 · +60.00%"
    )
    rendered = str(payload)
    assert "+112.00%" not in rendered
    assert "09/03" not in rendered


@pytest.mark.asyncio
async def test_simple_swing_uses_shared_fixed_tps_without_short_term_exit_logic() -> None:
    database, trade = await swing_database()
    policy = ShortTermTrackingPolicy.load(POLICY_PATH)
    service = SwingTrackingService(database, policy, None)
    try:
        await service.register_trade(trade.id, Decimal("1.00"))
        async with database.session() as session:
            tracking = await session.scalar(select(SwingTracking))
        assert tracking is not None
        first = datetime(2026, 9, 3, 14, 30, tzinfo=UTC)
        await service.process_price(tracking.id, quote(tracking, "1.80", first))
        await service.process_price(
            tracking.id, quote(tracking, "1.60", first + timedelta(minutes=1))
        )
        await service.process_price(tracking.id, quote(tracking, "0.70", first + timedelta(days=1)))

        async with database.session() as session:
            current = await session.get(SwingTracking, tracking.id)
            events = list(
                await session.scalars(
                    select(SwingTrackingEvent).order_by(SwingTrackingEvent.created_at)
                )
            )
            snapshots = list(await session.scalars(select(SwingDailySnapshot)))
        assert current is not None
        assert current.tracking_state == "ACTIVE"
        assert current.tracking_policy_version == policy.version
        assert current.tp_levels_hit == ["TP1", "TP2", "TP3", "TP4"]
        assert current.highest_tp_level == "TP4"
        assert current.highest_price == Decimal("1.8000")
        assert current.lowest_price == Decimal("0.7000")
        assert [event.event_type for event in events].count("FIXED_TP_HIT") == 4
        assert not {"FAST_MOMENTUM_REVERSAL", "TRACKING_STOPPED"} & {
            event.event_type for event in events
        }
        assert len(snapshots) == 2

        active = await service.active_positions(GUILD_ID)
        assert len(active) == 1
        assert active[0].highest_tp_level == "TP4"
        assert active[0].highest_tp_return_pct == 75
        assert active[0].highest_return_pct == Decimal("80.0000")
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_manual_close_keeps_lifecycle_high_and_stops_tracking() -> None:
    database, trade = await swing_database()
    service = SwingTrackingService(database, ShortTermTrackingPolicy.load(POLICY_PATH), None)
    try:
        await service.register_trade(trade.id, Decimal("2.00"))
        async with database.session() as session:
            tracking = await session.scalar(select(SwingTracking))
        assert tracking is not None
        now = datetime.now(UTC)
        await service.process_price(tracking.id, quote(tracking, "4.00", now))
        await service.close_trade(
            trade.id,
            reference_price=Decimal("3.00"),
            reference_source="MANAGER_INPUT",
        )
        async with database.session() as session:
            current = await session.get(SwingTracking, tracking.id)
            close_event = await session.scalar(
                select(SwingTrackingEvent).where(
                    SwingTrackingEvent.event_type == "MANUAL_SIGNAL_CLOSE"
                )
            )
        assert current is not None and close_event is not None
        assert current.tracking_state == "STOPPED"
        assert current.highest_return_pct == Decimal("100.0000")
        assert current.close_reference_return_pct == Decimal("50.0000")
        assert close_event.high_watermark_return_pct == Decimal("100.0000")
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_legacy_swing_cannot_enter_simple_tracker() -> None:
    database, trade = await swing_database(mode="LEGACY_SWING")
    service = SwingTrackingService(database, ShortTermTrackingPolicy.load(POLICY_PATH), None)
    try:
        with pytest.raises(SwingTrackingError, match="SIMPLE_SWING_TRADE_INVALID"):
            await service.register_trade(trade.id, Decimal("1.00"))
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_simple_swing_entry_and_reviewed_close_publication_lifecycle() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    policy = ShortTermTrackingPolicy.load(POLICY_PATH)
    tracker = SwingTrackingService(database, policy, None)
    publications = TradePublicationService(database)
    try:
        async with database.session() as session:
            session.add(GuildConfig(guild_id=GUILD_ID, swing_channel_id=103))
            source = SourceMessage(
                guild_id=GUILD_ID,
                discord_message_id=501,
                channel_id=502,
                submitted_by=503,
                raw_text="swing TSLA 10/16 400C @2.00",
                status=SourceStatus.PARSED.value,
                received_at=datetime.now(UTC),
            )
            session.add(source)
            await session.flush()
            entry = TradeDraft(
                guild_id=GUILD_ID,
                draft_code="S-00001",
                source_message_id=source.id,
                status=DraftStatus.READY.value,
                intent="NEW_TRADE",
                action="ENTRY",
                action_stage="NONE",
                category_suggestion="SWING",
                selected_category="SWING",
                ticker="TSLA",
                expiry=date.today() + timedelta(days=30),
                expiry_input=(date.today() + timedelta(days=30)).isoformat(),
                expiry_precision="EXACT_DATE",
                expiry_resolution_status="EXPLICIT",
                option_contract_code="O:TSLA261016C00400000",
                contract_validation_status="VALID",
                strike=Decimal("400"),
                option_side="CALL",
                entry_low=Decimal("2.00"),
                entry_high=Decimal("2.00"),
                parse_payload={"_swing_mode": SIMPLE_TRACKED_SWING},
                missing_fields=[],
                warnings=[],
                reviewed_by=503,
                version=2,
            )
            session.add(entry)
            await session.commit()

        entry_claim = await publications.claim(entry.id)
        assert isinstance(entry_claim.card, SwingTrackedEntryCard)
        assert entry_claim.claim_token is not None
        result = await publications.finalize(
            entry_claim.publication_id,
            claim_token=entry_claim.claim_token,
            message_id=601,
        )
        await tracker.register_trade(result.trade_id, entry_claim.card.entry_price)
        async with database.session() as session:
            tracking = await session.scalar(select(SwingTracking))
        assert tracking is not None
        await tracker.process_price(
            tracking.id,
            quote(tracking, "4.00", datetime.now(UTC) + timedelta(seconds=1)),
        )

        async with database.session() as session:
            source = SourceMessage(
                guild_id=GUILD_ID,
                discord_message_id=504,
                channel_id=502,
                submitted_by=503,
                raw_text="close SW-0001",
                status=SourceStatus.PARSED.value,
                received_at=datetime.now(UTC),
            )
            session.add(source)
            await session.flush()
            close = TradeDraft(
                guild_id=GUILD_ID,
                draft_code="S-00002",
                source_message_id=source.id,
                matched_trade_id=result.trade_id,
                status=DraftStatus.READY.value,
                intent="UPDATE_TRADE",
                action="CLOSE",
                action_stage="NONE",
                action_price=Decimal("3.00"),
                category_suggestion="SWING",
                selected_category="SWING",
                ticker="TSLA",
                expiry=entry.expiry,
                expiry_input=entry.expiry_input,
                expiry_precision="EXACT_DATE",
                expiry_resolution_status="EXPLICIT",
                option_contract_code="O:TSLA261016C00400000",
                contract_validation_status="VALID",
                strike=Decimal("400"),
                option_side="CALL",
                position_after_eighths=0,
                parse_payload={"_swing_mode": SIMPLE_TRACKED_SWING},
                missing_fields=[],
                warnings=[],
                reviewed_by=503,
                version=2,
            )
            session.add(close)
            await session.commit()

        close_claim = await publications.claim(close.id)
        assert isinstance(close_claim.card, SwingTrackingCard)
        assert close_claim.card.highest_return_pct == Decimal("100.0000")
        close_embed = build_swing_tracking_embed(close_claim.card).to_dict()
        assert close_embed["fields"][0]["name"] == "平仓结果"
        assert close_embed["fields"][0]["value"] == (
            "$2 → 最高 +100.00% → 平仓 +50.00%"
        )
        assert close_claim.claim_token is not None
        await publications.finalize(
            close_claim.publication_id,
            claim_token=close_claim.claim_token,
            message_id=602,
        )
        await tracker.close_trade(
            result.trade_id,
            reference_price=close_claim.card.price,
            reference_source="LAST_VALID",
        )
        async with database.session() as session:
            trade = await session.get(Trade, result.trade_id)
            tracking = await session.scalar(select(SwingTracking))
        assert trade is not None and tracking is not None
        assert trade.state == "CLOSED"
        assert trade.final_return_pct == Decimal("100.0000")
        assert tracking.tracking_state == "STOPPED"
        assert await publications.current_orders(GUILD_ID, "SWING") == []
    finally:
        await database.dispose()
