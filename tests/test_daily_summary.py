from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.bot.cards import build_daily_results_embed, build_daily_summary_embeds
from app.db.base import Base
from app.db.bootstrap import seed_guild_config
from app.db.models import (
    DailyResultsPublication,
    DailySummaryPublication,
    MarketQuoteSnapshot,
    Mentor,
    Trade,
    TradeEvent,
)
from app.db.session import Database
from app.domain.enums import OptionSide, PublicationStatus, TradeCategory, TradeState
from app.domain.public_cards import DailyResultRow, DailyResultsCard
from app.integrations.moomoo_market_data import (
    OptionQuote,
    OptionQuoteRequest,
    PostCloseQuoteBatch,
)
from app.services.daily_summary import DailySummaryService, scheduled_session_date

GUILD_ID = 1543309921066684567
SESSION_DATE = date(2026, 8, 28)


class FakeMarketData:
    def __init__(self, *, is_trading_session: bool = True) -> None:
        self.is_trading_session = is_trading_session
        self.calls = 0

    async def fetch_post_close(
        self,
        requests: tuple[OptionQuoteRequest, ...],
        *,
        session_date: date,
    ) -> PostCloseQuoteBatch:
        self.calls += 1
        quotes = tuple(
            OptionQuote(
                key=request.key,
                instrument_code="US.AAPL260918C200000",
                last_price=Decimal("1.50"),
                quote_time=datetime(2026, 8, 28, 20, 5, tzinfo=UTC),
            )
            for request in requests
        )
        return PostCloseQuoteBatch(
            session_date=session_date,
            market_state="AFTER_HOURS_BEGIN",
            is_trading_session=self.is_trading_session,
            quotes=quotes,
        )


def discord_ids() -> dict[str, object]:
    return {
        "guild_id": GUILD_ID,
        "roles": {"manager": 101, "member": 102},
        "channels": {
            "official_results": 201,
            "short_term_alerts": 202,
            "swing_alerts": 203,
            "leaps_alerts": 204,
            "mentor_control": 205,
            "member_control": 206,
        },
    }


async def seeded_database() -> Database:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with database.session() as session:
        await seed_guild_config(session, guild_id=GUILD_ID, discord_ids=discord_ids())
        mentor = Mentor(guild_id=GUILD_ID, name="Internal Mentor", short_code="INT")
        session.add(mentor)
        await session.flush()
        active = Trade(
            guild_id=GUILD_ID,
            public_trade_id="SW-0002",
            category=TradeCategory.SWING.value,
            mentor_id=mentor.id,
            ticker="AAPL",
            expiry=date(2026, 9, 18),
            strike=Decimal("200"),
            option_side=OptionSide.CALL.value,
            state=TradeState.ACTIVE.value,
            position_eighths=2,
            max_position_eighths=2,
            avg_cost=Decimal("1.20"),
            is_lotto=True,
        )
        closed = Trade(
            guild_id=GUILD_ID,
            public_trade_id="SW-0001",
            category=TradeCategory.SWING.value,
            mentor_id=mentor.id,
            ticker="SPY",
            expiry=date(2026, 9, 18),
            strike=Decimal("770"),
            option_side=OptionSide.PUT.value,
            state=TradeState.CLOSED.value,
            position_eighths=0,
            max_position_eighths=1,
            closed_at=datetime(2026, 8, 28, 19, 30, tzinfo=UTC),
            is_lotto=True,
        )
        session.add_all([active, closed])
        await session.flush()
        session.add_all(
            [
                TradeEvent(
                    trade_id=closed.id,
                    action="ENTRY",
                    action_stage="NONE",
                    price=Decimal("2.00"),
                    position_delta_eighths=1,
                    position_after_eighths=1,
                    approved_by=999,
                ),
                TradeEvent(
                    trade_id=closed.id,
                    action="CLOSE",
                    action_stage="NONE",
                    price=Decimal("3.00"),
                    position_delta_eighths=-1,
                    position_after_eighths=0,
                    approved_by=999,
                ),
            ]
        )
        await session.commit()
    return database


@pytest.mark.asyncio
async def test_prepare_is_idempotent_and_public_payload_is_strict() -> None:
    database = await seeded_database()
    market = FakeMarketData()
    service = DailySummaryService(database, market)
    try:
        assert await service.prepare_session(GUILD_ID, SESSION_DATE) is True
        assert await service.prepare_session(GUILD_ID, SESSION_DATE) is True
        assert market.calls == 1
        async with database.session() as session:
            assert (
                await session.scalar(select(func.count()).select_from(DailySummaryPublication)) == 2
            )
            assert await session.scalar(select(func.count()).select_from(MarketQuoteSnapshot)) == 1
            assert (
                await session.scalar(select(func.count()).select_from(DailyResultsPublication)) == 1
            )
            payloads = list(await session.scalars(select(DailySummaryPublication.snapshot_json)))
            public_text = str(payloads)
            assert "Internal Mentor" not in public_text
            assert "mentor" not in public_text.lower()
            assert "source" not in public_text.lower()

        claims = []
        for message_id in (1001, 1002):
            claim = await service.next_publishable(GUILD_ID, SESSION_DATE)
            assert claim is not None
            claims.append(claim)
            await service.finalize(claim.publication_id, message_id)
        assert await service.next_publishable(GUILD_ID, SESSION_DATE) is None

        embeds = []
        for claim in claims:
            embeds.extend(build_daily_summary_embeds(claim.summary))
        all_card_text = str([embed.to_dict() for embed in embeds])
        assert "SWING · DAILY SUMMARY" in all_card_text
        assert "当前 +25.00%" in all_card_text
        assert "CLOSE +50.00%" in all_card_text
        assert "(LOTTO)" in all_card_text
        for forbidden in ("Mentor", "source", "Bid", "Ask", "Market"):
            assert forbidden not in all_card_text

        async with database.session() as session:
            statuses = set(await session.scalars(select(DailySummaryPublication.status)))
            assert statuses == {PublicationStatus.PUBLISHED.value}

        results = await service.next_results_publishable(GUILD_ID, SESSION_DATE)
        assert results is not None
        assert [row.public_trade_id for row in results.card.swing] == ["SW-0001"]
        assert results.card.swing[0].is_lotto is True
        assert all(row.public_trade_id != "SW-0002" for row in results.card.swing)
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_non_trading_day_does_not_create_summaries() -> None:
    database = await seeded_database()
    service = DailySummaryService(database, FakeMarketData(is_trading_session=False))
    try:
        assert await service.prepare_session(GUILD_ID, SESSION_DATE) is False
        async with database.session() as session:
            count = await session.scalar(select(func.count()).select_from(DailySummaryPublication))
            assert count == 0
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_results_review_mode_disables_legacy_direct_results_publication() -> None:
    database = await seeded_database()
    service = DailySummaryService(
        database,
        FakeMarketData(),
        results_review_enabled=True,
    )
    try:
        assert await service.prepare_session(GUILD_ID, SESSION_DATE) is True
        async with database.session() as session:
            count = await session.scalar(select(func.count()).select_from(DailyResultsPublication))
            assert count == 0
    finally:
        await database.dispose()


def test_schedule_uses_eastern_time_and_skips_weekends() -> None:
    assert scheduled_session_date(datetime(2026, 8, 28, 20, 14, tzinfo=UTC), "16:15") is None
    assert (
        scheduled_session_date(datetime(2026, 8, 28, 20, 15, tzinfo=UTC), "16:15") == SESSION_DATE
    )
    assert scheduled_session_date(datetime(2026, 8, 29, 21, 0, tzinfo=UTC), "16:15") is None


def test_daily_results_are_extreme_simple_and_include_lotto() -> None:
    card = DailyResultsCard(
        session_date=SESSION_DATE,
        short_term=(
            DailyResultRow(
                public_trade_id="ST-0001",
                ticker="NVDA",
                strike=Decimal("500"),
                option_side="CALL",
                displayed_result_pct=Decimal("136"),
                is_lotto=True,
            ),
            DailyResultRow(
                public_trade_id="ST-0002",
                ticker="QQQ",
                strike=Decimal("714"),
                option_side="CALL",
                displayed_result_pct=Decimal("-50"),
            ),
        ),
        swing=(
            DailyResultRow(
                public_trade_id="SW-0001",
                ticker="SPY",
                strike=Decimal("770"),
                option_side="PUT",
                tp_returns=(("TP1", Decimal("42")), ("TP2", Decimal("70"))),
                highest_return_pct=Decimal("84"),
            ),
        ),
        leaps=(
            DailyResultRow(
                public_trade_id="LP-0001",
                ticker="ACHR",
                strike=Decimal("7"),
                option_side="CALL",
                tp_returns=(("TP1", Decimal("51")), ("TP2", Decimal("102"))),
                highest_return_pct=Decimal("126"),
                is_lotto=True,
            ),
            DailyResultRow(
                public_trade_id="LP-0002",
                ticker="NVDA",
                strike=Decimal("220"),
                option_side="CALL",
                exit_label="SL",
                exit_return_pct=Decimal("-22"),
                highest_return_pct=Decimal("8"),
            ),
        ),
    )
    rendered = str(build_daily_results_embed(card).to_dict())
    assert "ST-0001** · NVDA 500C (LOTTO) · +136.00%" in rendered
    assert "ST-0002** · QQQ 714C · -50.00%" in rendered
    assert "TP1 +42.00% · TP2 +70.00% · 最高收益 +84.00%" in rendered
    assert "TP1 +51.00% · TP2 +102.00% · 最高收益 +126.00%" in rendered
    assert "SL -22.00% · 最高收益 +8.00%" in rendered
    assert "Past performance does not guarantee future results." in rendered
    for forbidden in ("Tracking End", "Maximum Drawdown", "胜率", "总计"):
        assert forbidden not in rendered
