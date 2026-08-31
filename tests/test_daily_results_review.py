from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.bot.cards import build_daily_results_snapshot_embed
from app.bot.views.results_review_views import ResultsReviewView
from app.db.base import Base
from app.db.models import (
    AuditLog,
    DailyResultsItem,
    DailyResultsReview,
    GuildConfig,
    ShortTermTracking,
    Trade,
    TradeEvent,
)
from app.db.session import Database
from app.services.daily_results_review import DailyResultsReviewService, ResultsReviewError

GUILD_ID = 1543309921066684567
TRADING_DATE = date(2026, 8, 28)
ENDED_AT = datetime(2026, 8, 28, 19, 45, tzinfo=UTC)


class EarlyCloseCalendar:
    def is_trading_day(self, value: date) -> bool:
        return value == TRADING_DATE

    def session_close(self, value: date) -> datetime:
        assert value == TRADING_DATE
        return datetime(2026, 8, 28, 17, 0, tzinfo=UTC)


async def review_database() -> Database:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with database.session() as session:
        session.add(
            GuildConfig(
                guild_id=GUILD_ID,
                results_channel_id=101,
                results_review_channel_id=102,
                short_term_channel_id=103,
                swing_channel_id=104,
                leaps_channel_id=105,
            )
        )
        short = Trade(
            guild_id=GUILD_ID,
            public_trade_id="ST-0001",
            category="SHORT_TERM",
            ticker="NVDA",
            expiry=date(2026, 8, 28),
            strike=Decimal("200"),
            option_side="CALL",
            state="ACTIVE",
            position_eighths=0,
            max_position_eighths=0,
            is_lotto=True,
        )
        short_active = Trade(
            guild_id=GUILD_ID,
            public_trade_id="ST-0002",
            category="SHORT_TERM",
            ticker="QQQ",
            expiry=date(2026, 8, 28),
            strike=Decimal("714"),
            option_side="CALL",
            state="ACTIVE",
            position_eighths=0,
            max_position_eighths=0,
        )
        swing = Trade(
            guild_id=GUILD_ID,
            public_trade_id="SW-0001",
            category="SWING",
            ticker="GOOGL",
            expiry=date(2026, 9, 18),
            strike=Decimal("400"),
            option_side="CALL",
            state="CLOSED",
            position_eighths=0,
            max_position_eighths=1,
            closed_at=ENDED_AT,
            final_return_pct=Decimal("70"),
        )
        leaps = Trade(
            guild_id=GUILD_ID,
            public_trade_id="LP-0001",
            category="LEAPS",
            ticker="RGTI",
            expiry=date(2027, 1, 15),
            strike=Decimal("35"),
            option_side="CALL",
            state="CLOSED",
            position_eighths=0,
            max_position_eighths=1,
            closed_at=ENDED_AT,
            final_return_pct=Decimal("-22"),
        )
        active_swing = Trade(
            guild_id=GUILD_ID,
            public_trade_id="SW-0002",
            category="SWING",
            ticker="SPY",
            expiry=date(2026, 9, 18),
            strike=Decimal("650"),
            option_side="PUT",
            state="ACTIVE",
            position_eighths=1,
            max_position_eighths=1,
        )
        session.add_all([short, short_active, swing, leaps, active_swing])
        await session.flush()
        session.add_all(
            [
                ShortTermTracking(
                    guild_id=GUILD_ID,
                    trade_id=short.id,
                    option_ticker="O:NVDA260828C00200000",
                    entry_price=Decimal("1"),
                    current_price=Decimal("2.36"),
                    current_return_pct=Decimal("136"),
                    highest_price=Decimal("2.36"),
                    highest_return_pct=Decimal("136"),
                    highest_at=ENDED_AT,
                    lowest_price=Decimal("0.5"),
                    lowest_return_pct=Decimal("-50"),
                    lowest_at=ENDED_AT,
                    tp_levels_hit=["TP1", "TP2", "TP3"],
                    momentum_tp_events=[],
                    tracking_protection_price=Decimal("1.5"),
                    tracking_protection_return_pct=Decimal("50"),
                    tracking_protection_reason="TP2_PROTECTION",
                    tracking_state="STOPPED",
                    tracking_end_reason="TRACKING_STOP",
                    tracking_end_price=Decimal("1.5"),
                    tracking_end_return_pct=Decimal("50"),
                    tracking_started_at=ENDED_AT - timedelta(hours=1),
                    tracking_ended_at=ENDED_AT,
                    overnight_count=0,
                    tracking_policy_version="TEST",
                    price_source="MID",
                ),
                ShortTermTracking(
                    guild_id=GUILD_ID,
                    trade_id=short_active.id,
                    option_ticker="O:QQQ260828C00714000",
                    entry_price=Decimal("1"),
                    current_price=Decimal("1.2"),
                    current_return_pct=Decimal("20"),
                    highest_price=Decimal("1.2"),
                    highest_return_pct=Decimal("20"),
                    highest_at=ENDED_AT,
                    lowest_price=Decimal("1"),
                    lowest_return_pct=Decimal("0"),
                    lowest_at=ENDED_AT,
                    tp_levels_hit=["TP1"],
                    momentum_tp_events=[],
                    tracking_protection_price=Decimal("1"),
                    tracking_protection_return_pct=Decimal("0"),
                    tracking_protection_reason="TP1_PROTECTION",
                    tracking_state="ACTIVE",
                    tracking_started_at=ENDED_AT - timedelta(hours=1),
                    overnight_count=0,
                    tracking_policy_version="TEST",
                    price_source="MID",
                ),
                TradeEvent(
                    trade_id=swing.id,
                    action="TP1",
                    action_stage="FIRST",
                    price=Decimal("2.84"),
                    position_delta_eighths=0,
                    position_after_eighths=1,
                    pnl_pct=Decimal("42"),
                    approved_by=1,
                ),
                TradeEvent(
                    trade_id=swing.id,
                    action="TP2",
                    action_stage="SECOND",
                    price=Decimal("3.2"),
                    position_delta_eighths=0,
                    position_after_eighths=1,
                    pnl_pct=Decimal("60"),
                    approved_by=1,
                ),
                TradeEvent(
                    trade_id=swing.id,
                    action="CLOSE",
                    action_stage="NONE",
                    price=Decimal("3.4"),
                    position_delta_eighths=-1,
                    position_after_eighths=0,
                    pnl_pct=Decimal("70"),
                    approved_by=1,
                ),
                TradeEvent(
                    trade_id=leaps.id,
                    action="SL",
                    action_stage="NONE",
                    price=Decimal("0.78"),
                    position_delta_eighths=-1,
                    position_after_eighths=0,
                    pnl_pct=Decimal("-22"),
                    approved_by=1,
                ),
            ]
        )
        await session.commit()
    return database


@pytest.mark.asyncio
async def test_prepare_review_is_idempotent_and_excludes_active_trades() -> None:
    database = await review_database()
    service = DailyResultsReviewService(database)
    try:
        first = await service.prepare_review(GUILD_ID, TRADING_DATE)
        second = await service.prepare_review(GUILD_ID, TRADING_DATE)
        assert first.id == second.id
        assert {item.public_trade_id for item in first.items} == {
            "ST-0001",
            "SW-0001",
            "LP-0001",
        }
        assert all(item.included for item in first.items)
        short = next(item for item in first.items if item.public_trade_id == "ST-0001")
        assert short.display_result_pct == Decimal("136.0000")
        rendered = str(first.snapshot)
        assert "(LOTTO)" in rendered
        assert "TP1 +42% · TP2 +60% · 最高收益 +70%" in rendered
        async with database.session() as session:
            assert await session.scalar(select(func.count()).select_from(DailyResultsReview)) == 1
            assert await session.scalar(select(func.count()).select_from(DailyResultsItem)) == 3
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_exclude_and_reinclude_never_delete_trade_history() -> None:
    database = await review_database()
    service = DailyResultsReviewService(database)
    try:
        review = await service.prepare_review(GUILD_ID, TRADING_DATE)
        item = next(item for item in review.items if item.public_trade_id == "SW-0001")
        await service.set_included(
            item.id,
            included=False,
            actor_user_id=99,
            reason="DATA_QUALITY_ISSUE",
        )
        excluded = await service.get_review(review.id)
        saved = next(current for current in excluded.items if current.id == item.id)
        assert saved.included is False
        assert saved.exclusion_reason == "DATA_QUALITY_ISSUE"
        assert "SW-0001" not in str(await service.current_public_snapshot(review.id))
        async with database.session() as session:
            assert await session.scalar(select(func.count()).select_from(Trade)) == 5
            assert await session.scalar(select(func.count()).select_from(TradeEvent)) == 4
            audit = await session.scalar(
                select(AuditLog).where(AuditLog.action_type == "DAILY_RESULTS_EXCLUDED")
            )
            assert audit is not None
            assert audit.after_json["reason"] == "DATA_QUALITY_ISSUE"
        await service.set_included(item.id, included=True, actor_user_id=99)
        included = await service.get_review(review.id)
        assert next(current for current in included.items if current.id == item.id).included
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_display_edit_and_result_correction_do_not_modify_trade() -> None:
    database = await review_database()
    service = DailyResultsReviewService(database)
    try:
        review = await service.prepare_review(GUILD_ID, TRADING_DATE)
        item = next(item for item in review.items if item.public_trade_id == "ST-0001")
        await service.edit_item_display(
            item.id,
            display_text="ST-0001 · NVDA 200C (LOTTO) +140%",
            actor_user_id=99,
        )
        await service.correct_result(
            item.id,
            corrected_value=Decimal("140"),
            reason="BAD_QUOTE",
            actor_user_id=99,
        )
        async with database.session() as session:
            trade = await session.get(Trade, item.trade_id)
            saved = await session.get(DailyResultsItem, item.id)
            assert trade is not None and trade.final_return_pct is None
            assert saved is not None
            assert saved.original_result_pct == Decimal("136.0000")
            assert saved.display_result_pct == Decimal("140.0000")
            actions = set(await session.scalars(select(AuditLog.action_type)))
            assert "DAILY_RESULTS_DISPLAY_EDITED" in actions
            assert "DAILY_RESULTS_RESULT_CORRECTED" in actions
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_publish_now_is_idempotent_and_final_snapshot_is_immutable() -> None:
    database = await review_database()
    service = DailyResultsReviewService(database)
    try:
        review = await service.prepare_review(GUILD_ID, TRADING_DATE)
        claim = await service.claim_publish(
            review.id,
            actor_user_id=99,
            scheduled=False,
        )
        assert claim.should_publish is True
        assert claim.public_ref == "DAILY-RESULTS-20260828"
        await service.finalize_publish(review.id, message_id=500, actor_user_id=99)
        again = await service.claim_publish(
            review.id,
            actor_user_id=99,
            scheduled=True,
        )
        assert again.should_publish is False
        assert again.message_id == 500
        async with database.session() as session:
            stored = await session.get(DailyResultsReview, review.id)
            assert stored is not None
            immutable = dict(stored.final_snapshot or {})
            assert stored.status == "PUBLISHED"
        with pytest.raises(ResultsReviewError, match="REVIEW_LOCKED"):
            await service.set_included(
                review.items[0].id,
                included=False,
                actor_user_id=99,
                reason="OTHER",
            )
        await service.correct_result(
            review.items[0].id,
            corrected_value=Decimal("150"),
            reason="PUBLIC CORRECTION",
            actor_user_id=99,
        )
        async with database.session() as session:
            stored = await session.get(DailyResultsReview, review.id)
            assert stored is not None
            assert stored.status == "CORRECTED"
            assert stored.final_snapshot == immutable
            action = await session.scalar(
                select(AuditLog).where(AuditLog.action_type == "DAILY_RESULTS_PUBLIC_CORRECTION")
            )
            assert action is not None
    finally:
        await database.dispose()


def test_early_close_uses_real_close_but_public_publish_stays_1615_et() -> None:
    service = DailyResultsReviewService(
        Database("sqlite+aiosqlite:///:memory:"),
        calendar=EarlyCloseCalendar(),  # type: ignore[arg-type]
    )
    assert (
        service.draft_ready_date(
            datetime(2026, 8, 28, 17, 0, 59, tzinfo=UTC),
            1,
        )
        is None
    )
    assert (
        service.draft_ready_date(
            datetime(2026, 8, 28, 17, 1, tzinfo=UTC),
            1,
        )
        == TRADING_DATE
    )
    assert service.scheduled_publish_at(TRADING_DATE) == datetime(
        2026,
        8,
        28,
        20,
        15,
        tzinfo=UTC,
    )


def test_results_review_view_and_public_card_are_minimal() -> None:
    view = ResultsReviewView(object(), uuid.uuid4())  # type: ignore[arg-type]
    assert [item.label for item in view.children] == [
        "MANAGE TRADES",
        "EDIT CARD",
        "PREVIEW",
        "PUBLISH NOW",
    ]
    snapshot = {
        "title": "AXIS DAILY RESULTS",
        "trading_date": "2026-08-28",
        "sections": [
            {"label": "SHORT-TERM", "lines": ["ST-0001 · NVDA 200C +136%"]},
            {"label": "SWING", "lines": []},
            {"label": "LEAPS", "lines": []},
        ],
        "footer": "Past performance does not guarantee future results.",
    }
    rendered = str(build_daily_results_snapshot_embed(snapshot, review=False).to_dict())
    assert "ST-0001 · NVDA 200C +136%" in rendered
    assert "Past performance does not guarantee future results." in rendered
    for forbidden in ("Win Rate", "Closed Count", "Winner Count", "Average Return"):
        assert forbidden not in rendered
