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
    DailyResultsPublication,
    DailySummaryPublication,
    GuildConfig,
    MarketQuoteSnapshot,
    ShortTermDailySnapshot,
    ShortTermTracking,
    ShortTermTrackingEvent,
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
    DailyResultRow,
    DailyResultsCard,
    ShortTermDailyRow,
    ShortTermDailySummary,
)
from app.integrations.moomoo_market_data import (
    MarketDataError,
    OptionQuoteRequest,
    PostCloseMarketData,
)
from app.services.trading_calendar import TradingCalendarService

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
    summary: DailyCategorySummary | ShortTermDailySummary


@dataclass(frozen=True, slots=True)
class DailyResultsClaim:
    publication_id: uuid.UUID
    channel_id: int
    public_ref: str
    card: DailyResultsCard


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


def _serialize_summary(
    summary: DailyCategorySummary | ShortTermDailySummary,
) -> dict[str, Any]:
    def clean(value: object) -> object:
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        return value

    if isinstance(summary, ShortTermDailySummary):
        return {
            "kind": "SHORT_TERM_TRACKING",
            "category": summary.category,
            "session_date": summary.session_date.isoformat(),
            "active": [
                {key: clean(value) for key, value in asdict(item).items()}
                for item in summary.active
            ],
            "ended": [
                {key: clean(value) for key, value in asdict(item).items()} for item in summary.ended
            ],
        }
    return {
        "kind": "STANDARD_TRADE",
        "category": summary.category,
        "session_date": summary.session_date.isoformat(),
        "active": [
            {key: clean(value) for key, value in asdict(item).items()} for item in summary.active
        ],
        "closed": [
            {key: clean(value) for key, value in asdict(item).items()} for item in summary.closed
        ],
    }


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _short_term_row(item: dict[str, Any]) -> ShortTermDailyRow:
    return ShortTermDailyRow(
        public_trade_id=str(item["public_trade_id"]),
        ticker=str(item["ticker"]),
        expiry=date.fromisoformat(str(item["expiry"])),
        strike=Decimal(str(item["strike"])),
        option_side=str(item["option_side"]),
        current_return_pct=_optional_decimal(item.get("current_return_pct")),
        tracking_end_return_pct=_optional_decimal(item.get("tracking_end_return_pct")),
        highest_return_pct=Decimal(str(item["highest_return_pct"])),
        lowest_return_pct=Decimal(str(item["lowest_return_pct"])),
    )


def _deserialize_summary(
    payload: dict[str, Any],
) -> DailyCategorySummary | ShortTermDailySummary:
    try:
        if payload.get("kind") == "SHORT_TERM_TRACKING":
            return ShortTermDailySummary(
                category=TradeCategory.SHORT_TERM.value,
                session_date=date.fromisoformat(str(payload["session_date"])),
                active=tuple(_short_term_row(item) for item in payload.get("active", [])),
                ended=tuple(_short_term_row(item) for item in payload.get("ended", [])),
            )
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


def _serialize_results(card: DailyResultsCard) -> dict[str, Any]:
    def row(item: DailyResultRow) -> dict[str, object]:
        return {
            key: str(value) if isinstance(value, Decimal) else value
            for key, value in asdict(item).items()
        }

    return {
        "session_date": card.session_date.isoformat(),
        "short_term": [row(item) for item in card.short_term],
        "swing": [row(item) for item in card.swing],
        "leaps": [row(item) for item in card.leaps],
    }


def _deserialize_results(payload: dict[str, Any]) -> DailyResultsCard:
    def rows(key: str) -> tuple[DailyResultRow, ...]:
        return tuple(
            DailyResultRow(
                public_trade_id=str(item["public_trade_id"]),
                ticker=str(item["ticker"]),
                strike=Decimal(str(item["strike"])),
                option_side=str(item["option_side"]),
                tracking_end_return_pct=_optional_decimal(item.get("tracking_end_return_pct")),
                maximum_return_pct=_optional_decimal(item.get("maximum_return_pct")),
                maximum_drawdown_pct=_optional_decimal(item.get("maximum_drawdown_pct")),
                mentor_final_return_pct=_optional_decimal(item.get("mentor_final_return_pct")),
            )
            for item in payload.get(key, [])
        )

    try:
        return DailyResultsCard(
            session_date=date.fromisoformat(str(payload["session_date"])),
            short_term=rows("short_term"),
            swing=rows("swing"),
            leaps=rows("leaps"),
        )
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise DailySummaryError("RESULTS_SNAPSHOT_INVALID") from exc


class DailySummaryService:
    def __init__(
        self,
        database: Database,
        market_data: PostCloseMarketData | None = None,
        calendar: TradingCalendarService | None = None,
    ) -> None:
        self.database = database
        self.market_data = market_data
        self.calendar = calendar or TradingCalendarService()

    async def prepare_session(self, guild_id: int, session_date: date) -> bool:
        if not self.calendar.is_trading_day(session_date):
            return False
        async with self.database.session() as session:
            existing = set(
                await session.scalars(
                    select(DailySummaryPublication.category).where(
                        DailySummaryPublication.guild_id == guild_id,
                        DailySummaryPublication.session_date == session_date,
                    )
                )
            )
            results_existing = await session.scalar(
                select(DailyResultsPublication.id).where(
                    DailyResultsPublication.guild_id == guild_id,
                    DailyResultsPublication.session_date == session_date,
                )
            )
            if existing == set(CATEGORIES) and results_existing is not None:
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
                        Trade.category.in_((TradeCategory.SWING.value, TradeCategory.LEAPS.value)),
                        Trade.state.in_((TradeState.ACTIVE.value, TradeState.RUNNER.value)),
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
                        Trade.category.in_((TradeCategory.SWING.value, TradeCategory.LEAPS.value)),
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
            tracking_rows = (
                await session.execute(
                    select(ShortTermTracking, Trade)
                    .join(Trade, Trade.id == ShortTermTracking.trade_id)
                    .where(
                        ShortTermTracking.guild_id == guild_id,
                        (
                            ShortTermTracking.tracking_state.in_(("ACTIVE", "OVERNIGHT_ACTIVE"))
                            | (
                                (ShortTermTracking.tracking_ended_at >= start)
                                & (ShortTermTracking.tracking_ended_at < end)
                            )
                        ),
                    )
                    .order_by(Trade.public_trade_id)
                )
            ).all()

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
        quotes: dict[str, Any] = {}
        market_state = "UNAVAILABLE"
        if self.market_data is not None:
            try:
                batch = await self.market_data.fetch_post_close(requests, session_date=session_date)
            except MarketDataError as exc:
                raise DailySummaryError(exc.code) from exc
            if not batch.is_trading_session:
                return False
            quotes = {quote.key: quote for quote in batch.quotes}
            market_state = batch.market_state
        events_by_trade: dict[uuid.UUID, list[TradeEvent]] = {}
        for event in events:
            events_by_trade.setdefault(event.trade_id, []).append(event)

        short_term_active: list[ShortTermDailyRow] = []
        short_term_ended: list[ShortTermDailyRow] = []
        for tracking, trade in tracking_rows:
            row = ShortTermDailyRow(
                public_trade_id=trade.public_trade_id,
                ticker=trade.ticker,
                expiry=trade.expiry,
                strike=trade.strike,
                option_side=trade.option_side,
                current_return_pct=tracking.current_return_pct,
                tracking_end_return_pct=tracking.tracking_end_return_pct,
                highest_return_pct=tracking.highest_return_pct,
                lowest_return_pct=tracking.lowest_return_pct,
            )
            if tracking.tracking_state in {"ACTIVE", "OVERNIGHT_ACTIVE"}:
                short_term_active.append(row)
            else:
                short_term_ended.append(row)

        summaries: list[DailyCategorySummary | ShortTermDailySummary] = [
            ShortTermDailySummary(
                category=TradeCategory.SHORT_TERM.value,
                session_date=session_date,
                active=tuple(short_term_active),
                ended=tuple(short_term_ended),
            )
        ]
        for category in (TradeCategory.SWING.value, TradeCategory.LEAPS.value):
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
                            market_state=market_state,
                            quote_time=quote.quote_time,
                        )
                    )
            for tracking, _trade in tracking_rows:
                current = await session.get(ShortTermTracking, tracking.id)
                if current is None:
                    continue
                snapshot = await session.scalar(
                    select(ShortTermDailySnapshot).where(
                        ShortTermDailySnapshot.tracking_id == current.id,
                        ShortTermDailySnapshot.session_date == session_date,
                    )
                )
                if snapshot is not None:
                    continue
                session.add(
                    ShortTermDailySnapshot(
                        guild_id=guild_id,
                        tracking_id=current.id,
                        trade_id=current.trade_id,
                        session_date=session_date,
                        closing_price=current.current_price,
                        closing_return_pct=current.current_return_pct,
                        highest_price=current.highest_price,
                        highest_return_pct=current.highest_return_pct,
                        lowest_price=current.lowest_price,
                        lowest_return_pct=current.lowest_return_pct,
                        reference_protection_price=current.reference_protection_price,
                        tracking_state=current.tracking_state,
                        tracking_end_reason=current.tracking_end_reason,
                    )
                )
                if current.tracking_state not in {"ACTIVE", "OVERNIGHT_ACTIVE"}:
                    continue
                now = utc_now()
                current.closing_price = current.current_price
                current.closing_return_pct = current.current_return_pct
                current.tracking_state = "OVERNIGHT_ACTIVE"
                current.overnight_count += 1
                current.version += 1
                session.add(
                    ShortTermTrackingEvent(
                        guild_id=guild_id,
                        tracking_id=current.id,
                        trade_id=current.trade_id,
                        event_key=f"OVERNIGHT:{session_date.isoformat()}",
                        event_type="OVERNIGHT_CARRY",
                        source_market_timestamp=current.last_quote_at or now,
                        received_at=now,
                        price=current.current_price or current.entry_price,
                        return_pct=current.current_return_pct or Decimal("0"),
                        high_watermark_price=current.highest_price,
                        high_watermark_return_pct=current.highest_return_pct,
                        high_watermark_at=current.highest_at,
                        low_watermark_price=current.lowest_price,
                        low_watermark_return_pct=current.lowest_return_pct,
                        reference_protection_price=current.reference_protection_price,
                        tracking_policy_version=current.tracking_policy_version,
                        price_source=current.price_source,
                        public_notification=False,
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
            if results_existing is None:
                short_results = tuple(
                    DailyResultRow(
                        public_trade_id=row.public_trade_id,
                        ticker=row.ticker,
                        strike=row.strike,
                        option_side=row.option_side,
                        tracking_end_return_pct=row.tracking_end_return_pct,
                        maximum_return_pct=row.highest_return_pct,
                        maximum_drawdown_pct=row.lowest_return_pct,
                    )
                    for row in short_term_ended
                )
                mentor_results: dict[str, list[DailyResultRow]] = {
                    TradeCategory.SWING.value: [],
                    TradeCategory.LEAPS.value: [],
                }
                for trade in closed_trades:
                    final_return = trade.final_return_pct
                    if final_return is None:
                        final_return = _weighted_return(events_by_trade.get(trade.id, []))
                    mentor_results[trade.category].append(
                        DailyResultRow(
                            public_trade_id=trade.public_trade_id,
                            ticker=trade.ticker,
                            strike=trade.strike,
                            option_side=trade.option_side,
                            mentor_final_return_pct=final_return,
                        )
                    )
                results_card = DailyResultsCard(
                    session_date=session_date,
                    short_term=short_results,
                    swing=tuple(mentor_results[TradeCategory.SWING.value]),
                    leaps=tuple(mentor_results[TradeCategory.LEAPS.value]),
                )
                if config.results_channel_id is None:
                    raise DailySummaryError("RESULTS_CHANNEL_NOT_CONFIGURED")
                session.add(
                    DailyResultsPublication(
                        guild_id=guild_id,
                        session_date=session_date,
                        channel_id=config.results_channel_id,
                        public_ref=f"DAILY-RESULTS-{session_date:%Y%m%d}",
                        status=PublicationStatus.PENDING.value,
                        snapshot_json=_serialize_results(results_card),
                        attempt_count=0,
                    )
                )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
        return True

    async def next_publishable(self, guild_id: int, session_date: date) -> DailySummaryClaim | None:
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

    async def next_results_publishable(
        self, guild_id: int, session_date: date
    ) -> DailyResultsClaim | None:
        async with self.database.session() as session:
            publication = await session.scalar(
                select(DailyResultsPublication)
                .where(
                    DailyResultsPublication.guild_id == guild_id,
                    DailyResultsPublication.session_date == session_date,
                    DailyResultsPublication.status.in_(
                        (PublicationStatus.PENDING.value, PublicationStatus.FAILED.value)
                    ),
                )
                .with_for_update()
            )
            if publication is None:
                return None
            publication.status = PublicationStatus.PENDING.value
            publication.attempt_count += 1
            publication.last_error_code = None
            claim = DailyResultsClaim(
                publication_id=publication.id,
                channel_id=publication.channel_id,
                public_ref=publication.public_ref,
                card=_deserialize_results(publication.snapshot_json),
            )
            await session.commit()
            return claim

    async def mark_results_failed(self, publication_id: uuid.UUID, error_code: str) -> None:
        async with self.database.session() as session:
            publication = await session.get(DailyResultsPublication, publication_id)
            if publication is None:
                raise DailySummaryError("RESULTS_PUBLICATION_NOT_FOUND")
            if publication.status == PublicationStatus.PUBLISHED.value:
                return
            publication.status = PublicationStatus.FAILED.value
            publication.last_error_code = error_code[:64]
            await session.commit()

    async def finalize_results(self, publication_id: uuid.UUID, message_id: int) -> None:
        async with self.database.session() as session:
            publication = await session.get(DailyResultsPublication, publication_id)
            if publication is None:
                raise DailySummaryError("RESULTS_PUBLICATION_NOT_FOUND")
            if publication.status == PublicationStatus.PUBLISHED.value:
                return
            publication.message_id = message_id
            publication.status = PublicationStatus.PUBLISHED.value
            publication.last_error_code = None
            publication.published_at = utc_now()
            await session.commit()
