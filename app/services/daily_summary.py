from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    DailySummaryPublication,
    GuildConfig,
    MarketQuoteSnapshot,
    Trade,
    TradeEvent,
    utc_now,
)
from app.db.session import Database
from app.domain.enums import PublicationStatus, TradeCategory, TradeState
from app.domain.public_cards import (
    DailyActiveTrade,
    DailyCategorySummary,
    DailyClosedTrade,
)
from app.integrations.moomoo_market_data import (
    MarketDataError,
    OptionQuoteRequest,
    PostCloseMarketData,
)

ET = ZoneInfo("America/New_York")
CATEGORIES = (
    TradeCategory.SHORT_TERM.value,
    TradeCategory.SWING.value,
    TradeCategory.LEAPS.value,
)
PUBLIC_PREFIX = {
    TradeCategory.SHORT_TERM.value: "ST",
    TradeCategory.SWING.value: "SW",
    TradeCategory.LEAPS.value: "LP",
}


class DailySummaryError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class DailySummaryClaim:
    publication_id: uuid.UUID
    channel_id: int
    public_ref: str
    summary: DailyCategorySummary


def scheduled_session_date(now: datetime, schedule_hhmm: str) -> date | None:
    current = now.astimezone(ET)
    hour, minute = (int(part) for part in schedule_hhmm.split(":"))
    if current.weekday() >= 5 or current.time() < time(hour, minute):
        return None
    return current.date()


def _et_bounds(session_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(session_date, time.min, ET)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def _weighted_return(events: list[TradeEvent]) -> Decimal | None:
    entry_cost = Decimal("0")
    exit_value = Decimal("0")
    units = 0
    for event in events:
        delta = event.position_delta_eighths
        units += delta
        if delta == 0:
            continue
        if event.price is None:
            return None
        if delta > 0:
            entry_cost += event.price * delta
        else:
            exit_value += event.price * abs(delta)
    if entry_cost <= 0 or units != 0:
        return None
    return ((exit_value - entry_cost) / entry_cost) * Decimal("100")


def _serialize_summary(summary: DailyCategorySummary) -> dict[str, Any]:
    def clean(value: object) -> object:
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        return value

    return {
        "category": summary.category,
        "session_date": summary.session_date.isoformat(),
        "active": [
            {key: clean(value) for key, value in asdict(item).items()}
            for item in summary.active
        ],
        "closed": [
            {key: clean(value) for key, value in asdict(item).items()}
            for item in summary.closed
        ],
    }


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _deserialize_summary(payload: dict[str, Any]) -> DailyCategorySummary:
    try:
        active = tuple(
            DailyActiveTrade(
                public_trade_id=str(item["public_trade_id"]),
                ticker=str(item["ticker"]),
                expiry=date.fromisoformat(str(item["expiry"])),
                strike=Decimal(str(item["strike"])),
                option_side=str(item["option_side"]),
                position_eighths=int(item["position_eighths"]),
                avg_cost=_optional_decimal(item.get("avg_cost")),
                reference_price=_optional_decimal(item.get("reference_price")),
                unrealized_pnl_pct=_optional_decimal(item.get("unrealized_pnl_pct")),
                quote_time=(
                    datetime.fromisoformat(str(item["quote_time"]))
                    if item.get("quote_time")
                    else None
                ),
            )
            for item in payload.get("active", [])
        )
        closed = tuple(
            DailyClosedTrade(
                public_trade_id=str(item["public_trade_id"]),
                ticker=str(item["ticker"]),
                expiry=date.fromisoformat(str(item["expiry"])),
                strike=Decimal(str(item["strike"])),
                option_side=str(item["option_side"]),
                final_return_pct=_optional_decimal(item.get("final_return_pct")),
            )
            for item in payload.get("closed", [])
        )
        return DailyCategorySummary(
            category=str(payload["category"]),
            session_date=date.fromisoformat(str(payload["session_date"])),
            active=active,
            closed=closed,
        )
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise DailySummaryError("SUMMARY_SNAPSHOT_INVALID") from exc


class DailySummaryService:
    def __init__(self, database: Database, market_data: PostCloseMarketData) -> None:
        self.database = database
        self.market_data = market_data

    async def prepare_session(self, guild_id: int, session_date: date) -> bool:
        async with self.database.session() as session:
            existing = set(
                await session.scalars(
                    select(DailySummaryPublication.category).where(
                        DailySummaryPublication.guild_id == guild_id,
                        DailySummaryPublication.session_date == session_date,
                    )
                )
            )
            if existing == set(CATEGORIES):
                return True
            config = await session.get(GuildConfig, guild_id)
            if config is None:
                raise DailySummaryError("GUILD_CONFIG_NOT_FOUND")
            channels = {
                TradeCategory.SHORT_TERM.value: config.short_term_channel_id,
                TradeCategory.SWING.value: config.swing_channel_id,
                TradeCategory.LEAPS.value: config.leaps_channel_id,
            }
            if any(value is None for value in channels.values()):
                raise DailySummaryError("SUMMARY_CHANNEL_NOT_CONFIGURED")
            active_trades = list(
                await session.scalars(
                    select(Trade)
                    .where(
                        Trade.guild_id == guild_id,
                        Trade.state.in_(
                            (TradeState.ACTIVE.value, TradeState.RUNNER.value)
                        ),
                    )
                    .order_by(Trade.category, Trade.public_trade_id)
                )
            )
            start, end = _et_bounds(session_date)
            closed_trades = list(
                await session.scalars(
                    select(Trade)
                    .where(
                        Trade.guild_id == guild_id,
                        Trade.state == TradeState.CLOSED.value,
                        Trade.closed_at >= start,
                        Trade.closed_at < end,
                    )
                    .order_by(Trade.category, Trade.public_trade_id)
                )
            )
            closed_ids = [trade.id for trade in closed_trades]
            events = (
                list(
                    await session.scalars(
                        select(TradeEvent)
                        .where(TradeEvent.trade_id.in_(closed_ids))
                        .order_by(TradeEvent.trade_id, TradeEvent.created_at, TradeEvent.id)
                    )
                )
                if closed_ids
                else []
            )

        requests = tuple(
            OptionQuoteRequest(
                key=str(trade.id),
                ticker=trade.ticker,
                expiry=trade.expiry,
                strike=trade.strike,
                option_side=trade.option_side,
                instrument_code=trade.moomoo_option_code,
            )
            for trade in active_trades
        )
        try:
            batch = await self.market_data.fetch_post_close(
                requests, session_date=session_date
            )
        except MarketDataError as exc:
            raise DailySummaryError(exc.code) from exc
        if not batch.is_trading_session:
            return False
        quotes = {quote.key: quote for quote in batch.quotes}
        events_by_trade: dict[uuid.UUID, list[TradeEvent]] = {}
        for event in events:
            events_by_trade.setdefault(event.trade_id, []).append(event)

        summaries = []
        for category in CATEGORIES:
            active_rows = []
            for trade in active_trades:
                if trade.category != category:
                    continue
                quote = quotes.get(str(trade.id))
                reference = quote.last_price if quote is not None else None
                pnl = None
                if reference is not None and trade.avg_cost is not None and trade.avg_cost > 0:
                    pnl = ((reference - trade.avg_cost) / trade.avg_cost) * Decimal("100")
                active_rows.append(
                    DailyActiveTrade(
                        public_trade_id=trade.public_trade_id,
                        ticker=trade.ticker,
                        expiry=trade.expiry,
                        strike=trade.strike,
                        option_side=trade.option_side,
                        position_eighths=trade.position_eighths,
                        avg_cost=trade.avg_cost,
                        reference_price=reference,
                        unrealized_pnl_pct=pnl,
                        quote_time=quote.quote_time if quote is not None else None,
                    )
                )
            closed_rows = []
            for trade in closed_trades:
                if trade.category != category:
                    continue
                final_return = trade.final_return_pct
                if final_return is None:
                    final_return = _weighted_return(events_by_trade.get(trade.id, []))
                closed_rows.append(
                    DailyClosedTrade(
                        public_trade_id=trade.public_trade_id,
                        ticker=trade.ticker,
                        expiry=trade.expiry,
                        strike=trade.strike,
                        option_side=trade.option_side,
                        final_return_pct=final_return,
                    )
                )
            summaries.append(
                DailyCategorySummary(
                    category=category,
                    session_date=session_date,
                    active=tuple(active_rows),
                    closed=tuple(closed_rows),
                )
            )

        async with self.database.session() as session:
            for trade in active_trades:
                quote = quotes.get(str(trade.id))
                if quote is None:
                    continue
                current = await session.get(Trade, trade.id)
                if current is not None and quote.instrument_code:
                    current.moomoo_option_code = quote.instrument_code
                if (
                    quote.last_price is None
                    or quote.quote_time is None
                    or not quote.instrument_code
                ):
                    continue
                snapshot = await session.scalar(
                    select(MarketQuoteSnapshot).where(
                        MarketQuoteSnapshot.trade_id == trade.id,
                        MarketQuoteSnapshot.session_date == session_date,
                    )
                )
                if snapshot is None:
                    session.add(
                        MarketQuoteSnapshot(
                            guild_id=guild_id,
                            trade_id=trade.id,
                            session_date=session_date,
                            provider="MOOMOO",
                            instrument_code=quote.instrument_code,
                            last_price=quote.last_price,
                            market_state=batch.market_state,
                            quote_time=quote.quote_time,
                        )
                    )
            for summary in summaries:
                if summary.category in existing:
                    continue
                session.add(
                    DailySummaryPublication(
                        guild_id=guild_id,
                        category=summary.category,
                        session_date=session_date,
                        channel_id=int(channels[summary.category]),
                        public_ref=(
                            f"EOD-{PUBLIC_PREFIX[summary.category]}-"
                            f"{session_date.strftime('%Y%m%d')}"
                        ),
                        status=PublicationStatus.PENDING.value,
                        snapshot_json=_serialize_summary(summary),
                        attempt_count=0,
                    )
                )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
        return True

    async def next_publishable(
        self, guild_id: int, session_date: date
    ) -> DailySummaryClaim | None:
        async with self.database.session() as session:
            publication = await session.scalar(
                select(DailySummaryPublication)
                .where(
                    DailySummaryPublication.guild_id == guild_id,
                    DailySummaryPublication.session_date == session_date,
                    DailySummaryPublication.status.in_(
                        (PublicationStatus.PENDING.value, PublicationStatus.FAILED.value)
                    ),
                )
                .order_by(DailySummaryPublication.category)
                .limit(1)
                .with_for_update()
            )
            if publication is None:
                return None
            publication.status = PublicationStatus.PENDING.value
            publication.attempt_count += 1
            publication.last_error_code = None
            claim = DailySummaryClaim(
                publication_id=publication.id,
                channel_id=publication.channel_id,
                public_ref=publication.public_ref,
                summary=_deserialize_summary(publication.snapshot_json),
            )
            await session.commit()
            return claim

    async def mark_failed(self, publication_id: uuid.UUID, error_code: str) -> None:
        async with self.database.session() as session:
            publication = await session.get(DailySummaryPublication, publication_id)
            if publication is None:
                raise DailySummaryError("SUMMARY_PUBLICATION_NOT_FOUND")
            if publication.status == PublicationStatus.PUBLISHED.value:
                return
            publication.status = PublicationStatus.FAILED.value
            publication.last_error_code = error_code[:64]
            await session.commit()

    async def finalize(self, publication_id: uuid.UUID, message_id: int) -> None:
        async with self.database.session() as session:
            publication = await session.get(DailySummaryPublication, publication_id)
            if publication is None:
                raise DailySummaryError("SUMMARY_PUBLICATION_NOT_FOUND")
            if publication.status == PublicationStatus.PUBLISHED.value:
                return
            publication.message_id = message_id
            publication.status = PublicationStatus.PUBLISHED.value
            publication.last_error_code = None
            publication.published_at = utc_now()
            await session.commit()
