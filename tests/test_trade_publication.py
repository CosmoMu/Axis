from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.bot.cards import (
    build_active_orders_embed,
    build_public_trade_embed,
    build_short_term_entry_embed,
)
from app.bot.views.review_views import ActiveOrdersView
from app.db.base import Base
from app.db.models import (
    AuditLog,
    GuildConfig,
    Mentor,
    ShortTermTracking,
    SourceMessage,
    Trade,
    TradeDraft,
    TradeEvent,
    TradePublication,
)
from app.db.session import Database
from app.domain.enums import DraftStatus, PublicationStatus, SourceStatus, TradeState
from app.services.short_term_policy import ShortTermTrackingPolicy
from app.services.short_term_tracking import MarketTrackingService
from app.services.trade_publication import TradePublicationService

GUILD_ID = 1543309921066684567


async def publication_database() -> tuple[Database, TradeDraft]:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with database.session() as session:
        session.add(
            GuildConfig(
                guild_id=GUILD_ID,
                short_term_channel_id=101,
                swing_channel_id=102,
                leaps_channel_id=103,
            )
        )
        mentor = Mentor(guild_id=GUILD_ID, name="Private Mentor", short_code="PM")
        session.add(mentor)
        source = SourceMessage(
            guild_id=GUILD_ID,
            discord_message_id=201,
            channel_id=202,
            submitted_by=203,
            raw_text="private raw source",
            status=SourceStatus.PARSED.value,
            received_at=datetime.now(UTC),
        )
        session.add(source)
        await session.flush()
        draft = TradeDraft(
            guild_id=GUILD_ID,
            draft_code="D-PUBLISH",
            source_message_id=source.id,
            mentor_id=mentor.id,
            status=DraftStatus.READY.value,
            intent="NEW_TRADE",
            action="ENTRY",
            action_stage="NONE",
            selected_category="SWING",
            ticker="TSLA",
            expiry=date(2026, 9, 18),
            strike=Decimal("400"),
            option_side="CALL",
            entry_low=Decimal("3.20"),
            entry_high=Decimal("3.35"),
            sl=Decimal("2.55"),
            tp1=Decimal("4.10"),
            tp2=Decimal("5.00"),
            is_lotto=True,
            position_delta_eighths=1,
            position_after_eighths=1,
            parse_payload={
                "plan_current_stock": 398.5,
                "plan_starter": 398.0,
                "plan_add_zone_low": 392.0,
                "plan_add_zone_high": 395.0,
                "plan_stock_sl": 386.0,
                "plan_stock_pt1": 410.0,
                "plan_stock_pt2": 420.0,
                "plan_stock_pt3": 435.0,
                "plan_fib_0618": 390.5,
                "public_thesis": "结构守稳后观察目标推进。",
            },
            missing_fields=[],
            warnings=[],
            internal_notes="never public",
            reviewed_by=301,
            version=2,
        )
        session.add(draft)
        await session.commit()
    return database, draft


@pytest.mark.asyncio
async def test_publication_is_idempotent_and_active_view_is_public_only() -> None:
    database, draft = await publication_database()
    service = TradePublicationService(database)
    try:
        claim = await service.claim(draft.id, actor_user_id=301, interaction_id=401)
        repeated_pending = await service.claim(draft.id, actor_user_id=302, interaction_id=402)
        assert claim.should_publish is True
        assert claim.card is not None
        assert claim.card.public_trade_id == "SW-0001"
        assert claim.public_ref == "P-0001"
        assert claim.card.current_stock == Decimal("398.5")
        assert claim.card.stock_pt3 == Decimal("435.0")
        assert claim.card.fib_0618 == Decimal("390.5")
        assert repeated_pending.should_publish is False
        assert repeated_pending.already_published is False
        assert claim.claim_token is not None

        public_text = str(
            build_public_trade_embed(claim.card, public_ref=claim.public_ref).to_dict()
        )
        for forbidden in (
            "Private Mentor",
            "private raw source",
            "never public",
            "Mentor",
            "source_message_id",
            "parser_confidence",
            "Market",
            "Bid",
            "Ask",
            "Stop",
        ):
            assert forbidden not in public_text
        assert "查看当前订单" not in public_text
        assert "SL" in public_text
        assert "P-F" not in public_text
        assert "(LOTTO)" in public_text

        result = await service.finalize(
            claim.publication_id,
            claim_token=claim.claim_token,
            message_id=501,
        )
        repeated_result = await service.finalize(
            claim.publication_id,
            claim_token=claim.claim_token,
            message_id=501,
        )
        repeated_claim = await service.claim(draft.id)
        assert result == repeated_result
        assert repeated_claim.already_published is True

        orders = await service.current_orders(GUILD_ID, "SWING")
        active_text = str(build_active_orders_embed("SWING", orders).to_dict())
        assert len(orders) == 1
        assert orders[0].public_trade_id == "SW-0001"
        assert orders[0].avg_cost == Decimal("3.275")
        assert "当前波段订单" in active_text
        assert "最近持仓成本 $3.275" in active_text
        assert "(LOTTO)" in active_text
        assert "Private Mentor" not in active_text

        async with database.session() as session:
            trade = await session.get(Trade, result.trade_id)
            stored_draft = await session.get(TradeDraft, draft.id)
            publication = await session.get(TradePublication, claim.publication_id)
            event_count = await session.scalar(select(func.count()).select_from(TradeEvent))
            event_price = await session.scalar(select(TradeEvent.price).limit(1))
            audit_actions = (
                await session.scalars(
                    select(AuditLog.action_type).order_by(AuditLog.created_at, AuditLog.id)
                )
            ).all()
        assert trade is not None and trade.state == TradeState.ACTIVE.value
        assert trade.is_lotto is True
        assert trade.position_eighths == trade.max_position_eighths == 1
        assert stored_draft is not None and stored_draft.status == DraftStatus.PUBLISHED.value
        assert publication is not None
        assert publication.status == PublicationStatus.PUBLISHED.value
        assert publication.message_id == 501
        assert event_count == 1
        assert event_price == Decimal("3.275")
        assert audit_actions == ["TRADE_PUBLICATION_CLAIMED", "TRADE_PUBLISHED"]
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_failed_publication_can_be_reclaimed_without_duplicate_trade() -> None:
    database, draft = await publication_database()
    service = TradePublicationService(database)
    try:
        first = await service.claim(draft.id)
        assert first.claim_token is not None
        await service.mark_failed(
            first.publication_id,
            claim_token=first.claim_token,
            error_code="DISCORD_SEND_FAILED",
        )
        retry = await service.claim(draft.id)
        assert retry.should_publish is True
        assert retry.claim_token is not None and retry.claim_token != first.claim_token
        await service.finalize(
            retry.publication_id,
            claim_token=retry.claim_token,
            message_id=601,
        )
        async with database.session() as session:
            trade_count = await session.scalar(select(func.count()).select_from(Trade))
            publication_count = await session.scalar(
                select(func.count()).select_from(TradePublication)
            )
            publication = await session.get(TradePublication, retry.publication_id)
        assert trade_count == publication_count == 1
        assert publication is not None and publication.attempt_count == 2
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_update_event_changes_active_state_and_close_removes_order() -> None:
    database, entry_draft = await publication_database()
    service = TradePublicationService(database)
    try:
        entry_claim = await service.claim(entry_draft.id)
        assert entry_claim.claim_token is not None
        entry_result = await service.finalize(
            entry_claim.publication_id,
            claim_token=entry_claim.claim_token,
            message_id=701,
        )

        async with database.session() as session:
            mentor_id = await session.scalar(select(Mentor.id).limit(1))
            assert mentor_id is not None
            source = SourceMessage(
                guild_id=GUILD_ID,
                discord_message_id=211,
                channel_id=202,
                submitted_by=203,
                raw_text="add",
                status=SourceStatus.PARSED.value,
                received_at=datetime.now(UTC),
            )
            session.add(source)
            await session.flush()
            add_draft = TradeDraft(
                guild_id=GUILD_ID,
                draft_code="D-ADD",
                source_message_id=source.id,
                matched_trade_id=entry_result.trade_id,
                mentor_id=mentor_id,
                status=DraftStatus.READY.value,
                intent="UPDATE_TRADE",
                action="ADD",
                action_stage="FIRST",
                action_price=Decimal("3.05"),
                avg_cost=Decimal("3.18"),
                sl=Decimal("2.55"),
                position_delta_eighths=1,
                position_after_eighths=2,
                current_pnl_pct=Decimal("-4.1"),
                parse_payload={},
                missing_fields=[],
                warnings=[],
                reviewed_by=301,
                version=2,
            )
            session.add(add_draft)
            await session.commit()

        add_claim = await service.claim(add_draft.id)
        assert add_claim.card is not None
        assert add_claim.card.public_trade_id == "SW-0001"
        assert add_claim.card.ticker == "TSLA"
        assert add_claim.claim_token is not None
        await service.finalize(
            add_claim.publication_id,
            claim_token=add_claim.claim_token,
            message_id=702,
        )
        active = await service.current_orders(GUILD_ID, "SWING")
        assert len(active) == 1
        assert active[0].last_public_action == "ADD_FIRST"
        assert active[0].position_eighths == 2
        assert "第一次加仓" in str(build_active_orders_embed("SWING", active).to_dict())

        async with database.session() as session:
            mentor_id = await session.scalar(select(Mentor.id).limit(1))
            assert mentor_id is not None
            source = SourceMessage(
                guild_id=GUILD_ID,
                discord_message_id=212,
                channel_id=202,
                submitted_by=203,
                raw_text="close",
                status=SourceStatus.PARSED.value,
                received_at=datetime.now(UTC),
            )
            session.add(source)
            await session.flush()
            close_draft = TradeDraft(
                guild_id=GUILD_ID,
                draft_code="D-CLOSE",
                source_message_id=source.id,
                matched_trade_id=entry_result.trade_id,
                mentor_id=mentor_id,
                status=DraftStatus.READY.value,
                intent="UPDATE_TRADE",
                action="CLOSE",
                action_stage="NONE",
                action_price=Decimal("4.20"),
                position_delta_eighths=-2,
                position_after_eighths=0,
                current_pnl_pct=Decimal("31.25"),
                parse_payload={},
                missing_fields=[],
                warnings=[],
                reviewed_by=301,
                version=2,
            )
            session.add(close_draft)
            await session.commit()

        close_claim = await service.claim(close_draft.id)
        assert close_claim.claim_token is not None
        await service.finalize(
            close_claim.publication_id,
            claim_token=close_claim.claim_token,
            message_id=703,
        )
        assert await service.current_orders(GUILD_ID, "SWING") == []
        async with database.session() as session:
            trade = await session.get(Trade, entry_result.trade_id)
            event_count = await session.scalar(select(func.count()).select_from(TradeEvent))
        assert trade is not None and trade.state == TradeState.CLOSED.value
        assert trade.position_eighths == 0
        assert event_count == 3
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_active_order_buttons_use_fixed_persistent_custom_ids() -> None:
    controller = object()
    expected = {
        "SWING": "axis:active:swing:v1",
        "LEAPS": "axis:active:leaps:v1",
    }
    for category, custom_id in expected.items():
        view = ActiveOrdersView(controller, category)  # type: ignore[arg-type]
        assert view.is_persistent()
        assert len(view.children) == 1
        assert view.children[0].custom_id == custom_id
        assert view.children[0].label == "查看当前持仓订单"
    with pytest.raises(ValueError, match="ACTIVE_POSITION_VIEW_UNAVAILABLE"):
        ActiveOrdersView(controller, "SHORT_TERM")  # type: ignore[arg-type]


def test_roll_clears_cached_moomoo_contract_code() -> None:
    trade = Trade(
        guild_id=GUILD_ID,
        public_trade_id="SW-0001",
        category="SWING",
        mentor_id=uuid.uuid4(),
        ticker="SPY",
        expiry=date(2026, 9, 4),
        strike=Decimal("770"),
        option_side="CALL",
        moomoo_option_code="US.OLD-CONTRACT",
        state="ACTIVE",
        position_eighths=2,
        max_position_eighths=2,
        version=1,
    )
    draft = TradeDraft(
        action="ROLL",
        action_stage="NONE",
        ticker="SPY",
        expiry=date(2026, 9, 11),
        strike=Decimal("775"),
        option_side="CALL",
    )
    TradePublicationService._apply_trade_update(trade, draft, after_position=2)
    assert trade.moomoo_option_code is None
    assert trade.expiry == date(2026, 9, 11)


@pytest.mark.asyncio
async def test_short_term_publishes_without_mentor_and_registers_independent_tracking() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        async with database.session() as session:
            session.add(
                GuildConfig(
                    guild_id=GUILD_ID,
                    short_term_channel_id=101,
                    swing_channel_id=102,
                    leaps_channel_id=103,
                )
            )
            source = SourceMessage(
                guild_id=GUILD_ID,
                discord_message_id=999,
                channel_id=202,
                submitted_by=203,
                raw_text="NVDA 08/31 500C 1.20",
                status=SourceStatus.PARSED.value,
                received_at=datetime.now(UTC),
            )
            session.add(source)
            await session.flush()
            draft = TradeDraft(
                guild_id=GUILD_ID,
                draft_code="S-00999",
                source_message_id=source.id,
                mentor_id=None,
                status=DraftStatus.READY.value,
                intent="NEW_TRADE",
                action="ENTRY",
                selected_category="SHORT_TERM",
                ticker="NVDA",
                expiry=date(2027, 1, 15),
                strike=Decimal("500"),
                option_side="CALL",
                entry_low=Decimal("1.20"),
                entry_high=Decimal("1.20"),
                is_lotto=True,
                position_delta_eighths=None,
                position_after_eighths=None,
                parse_payload={},
                missing_fields=[],
                warnings=[],
                reviewed_by=301,
                version=2,
            )
            session.add(draft)
            await session.commit()

        publication = TradePublicationService(database)
        claim = await publication.claim(draft.id)
        assert claim.card is not None
        public_text = str(
            build_short_term_entry_embed(
                claim.card,  # type: ignore[arg-type]
                public_ref=claim.public_ref,
            ).to_dict()
        )
        for forbidden in ("Mentor", "SL", "TP", "仓位", "Market", "Bid", "Ask"):
            assert forbidden not in public_text
        assert "MY RISK IS NOT YOUR RISK" in public_text
        assert "(LOTTO)" in public_text
        assert claim.claim_token is not None
        result = await publication.finalize(
            claim.publication_id,
            claim_token=claim.claim_token,
            message_id=9999,
        )

        tracker = MarketTrackingService(
            database,
            ShortTermTrackingPolicy.load(
                Path(__file__).resolve().parents[1] / "config" / "short_term_tracking.yaml"
            ),
            None,
        )
        await tracker.register_trade(result.trade_id, Decimal("1.20"))
        await tracker.register_trade(result.trade_id, Decimal("1.20"))
        async with database.session() as session:
            saved_trade = await session.get(Trade, result.trade_id)
            tracking_count = await session.scalar(
                select(func.count()).select_from(ShortTermTracking)
            )
        assert saved_trade is not None
        assert saved_trade.is_lotto is True
        assert saved_trade.mentor_id is None
        assert saved_trade.position_eighths == 0
        assert saved_trade.state == TradeState.ACTIVE.value
        assert tracking_count == 1
    finally:
        await database.dispose()
