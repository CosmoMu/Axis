from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.bot.cards import build_daily_summary_embeds, build_short_term_daily_summary_embed
from app.db.base import Base
from app.db.bootstrap import seed_guild_config
from app.db.models import (
    DailySummaryPublication,
    MarketQuoteSnapshot,
    Mentor,
    Trade,
    TradeEvent,
)
from app.db.session import Database
from app.domain.enums import OptionSide, PublicationStatus, TradeCategory, TradeState
from app.domain.public_cards import ShortTermDailySummary
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
                await session.scalar(select(func.count()).select_from(DailySummaryPublication)) == 3
            )
            assert await session.scalar(select(func.count()).select_from(MarketQuoteSnapshot)) == 1
            payloads = list(await session.scalars(select(DailySummaryPublication.snapshot_json)))
            public_text = str(payloads)
            assert "Internal Mentor" not in public_text
            assert "mentor" not in public_text.lower()
            assert "source" not in public_text.lower()

        claims = []
        for message_id in (1001, 1002, 1003):
            claim = await service.next_publishable(GUILD_ID, SESSION_DATE)
            assert claim is not None
            claims.append(claim)
            await service.finalize(claim.publication_id, message_id)
        assert await service.next_publishable(GUILD_ID, SESSION_DATE) is None

        embeds = []
        for claim in claims:
            if isinstance(claim.summary, ShortTermDailySummary):
                embeds.append(build_short_term_daily_summary_embed(claim.summary))
            else:
                embeds.extend(build_daily_summary_embeds(claim.summary))
        all_card_text = str([embed.to_dict() for embed in embeds])
        assert "当前/收盘参考价" in all_card_text
        assert "浮动 +25.00%" in all_card_text
        assert "加权最终收益 +50.00%" in all_card_text
        for forbidden in ("Mentor", "source", "Bid", "Ask", "Market"):
            assert forbidden not in all_card_text

        async with database.session() as session:
            statuses = set(await session.scalars(select(DailySummaryPublication.status)))
            assert statuses == {PublicationStatus.PUBLISHED.value}
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


def test_schedule_uses_eastern_time_and_skips_weekends() -> None:
    assert scheduled_session_date(datetime(2026, 8, 28, 20, 14, tzinfo=UTC), "16:15") is None
    assert (
        scheduled_session_date(datetime(2026, 8, 28, 20, 15, tzinfo=UTC), "16:15") == SESSION_DATE
    )
    assert scheduled_session_date(datetime(2026, 8, 29, 21, 0, tzinfo=UTC), "16:15") is None
