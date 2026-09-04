from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    GuildConfig,
    MarketQuoteSnapshot,
    SwingDailySnapshot,
    SwingTracking,
    SwingTrackingEvent,
    Trade,
    TradeEvent,
    TradePublication,
    utc_now,
)
from app.db.session import Database
from app.domain.public_cards import SwingActivePosition, SwingTrackingCard
from app.integrations.massive_market_data import (
    MarketDataProvider,
    MarketDataProviderError,
    MarketPrice,
    MarketPriceRequest,
    massive_option_ticker,
)
from app.services.short_term_policy import ShortTermTrackingPolicy
from app.services.trading_calendar import TradingCalendarService

ET = ZoneInfo("America/New_York")
SIMPLE_TRACKED_SWING = "SIMPLE_TRACKED_SWING"
LEGACY_SWING = "LEGACY_SWING"
RECOVERABLE_ERRORS = {
    "LAST_TRADE_OUTLIER",
    "MASSIVE_PRICE_UNAVAILABLE",
    "MASSIVE_QUOTE_STALE",
    "OPTION_CONTRACT_NOT_FOUND",
}

logger = logging.getLogger(__name__)


class SwingTrackingError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class SwingEventClaim:
    event_id: uuid.UUID
    channel_id: int
    public_ref: str
    card: SwingTrackingCard


class SwingTrackingService:
    """Independent Swing V2 tracker sharing only the active Short-Term TP policy."""

    def __init__(
        self,
        database: Database,
        policy: ShortTermTrackingPolicy,
        provider: MarketDataProvider | None,
        calendar: TradingCalendarService | None = None,
        historical_policies: Sequence[ShortTermTrackingPolicy] = (),
    ) -> None:
        self.database = database
        self.policy = policy
        self.provider = provider
        self.calendar = calendar or TradingCalendarService()
        self.policies = {item.version: item for item in (*historical_policies, policy)}

    @property
    def enabled(self) -> bool:
        return self.provider is not None

    async def register_trade(self, trade_id: uuid.UUID, entry_price: Decimal) -> None:
        if entry_price <= 0:
            raise SwingTrackingError("SWING_ENTRY_PRICE_REQUIRED")
        async with self.database.session() as session:
            if await session.scalar(
                select(SwingTracking.id).where(SwingTracking.trade_id == trade_id)
            ):
                return
            trade = await session.get(Trade, trade_id)
            if (
                trade is None
                or trade.category != "SWING"
                or trade.tracking_mode != SIMPLE_TRACKED_SWING
                or trade.mentor_id is not None
            ):
                raise SwingTrackingError("SIMPLE_SWING_TRADE_INVALID")
            now = utc_now()
            tracking = SwingTracking(
                guild_id=trade.guild_id,
                trade_id=trade.id,
                option_ticker=trade.option_contract_code
                or massive_option_ticker(
                    trade.ticker, trade.expiry, trade.strike, trade.option_side
                ),
                entry_price=entry_price,
                current_price=entry_price,
                current_return_pct=Decimal("0"),
                highest_price=entry_price,
                highest_return_pct=Decimal("0"),
                highest_at=now,
                lowest_price=entry_price,
                lowest_return_pct=Decimal("0"),
                lowest_at=now,
                tp_levels_hit=[],
                highest_tp_level=None,
                tracking_state="ACTIVE",
                tracking_started_at=now,
                last_session_date=now.astimezone(ET).date(),
                tracking_policy_version=self.policy.version,
                price_source=self.policy.price_source,
                consecutive_data_errors=0,
                version=1,
            )
            session.add(tracking)
            await session.flush()
            session.add(
                self._event(
                    tracking, "ENTRY_PUBLISHED", "ENTRY", now, now, entry_price, Decimal("0")
                )
            )
            await session.commit()

    async def register_missing(self, guild_id: int) -> int:
        await self.reconcile_closed_trades(guild_id)
        async with self.database.session() as session:
            rows = (
                await session.execute(
                    select(Trade.id, TradeEvent.price)
                    .join(TradePublication, TradePublication.trade_id == Trade.id)
                    .join(TradeEvent, TradeEvent.id == TradePublication.trade_event_id)
                    .outerjoin(SwingTracking, SwingTracking.trade_id == Trade.id)
                    .where(
                        Trade.guild_id == guild_id,
                        Trade.category == "SWING",
                        Trade.tracking_mode == SIMPLE_TRACKED_SWING,
                        TradePublication.status == "PUBLISHED",
                        SwingTracking.id.is_(None),
                        TradeEvent.action == "ENTRY",
                        TradeEvent.price.is_not(None),
                    )
                )
            ).all()
        count = 0
        for trade_id, entry_price in rows:
            try:
                await self.register_trade(trade_id, entry_price)
                count += 1
            except IntegrityError:
                continue
        return count

    async def reconcile_closed_trades(self, guild_id: int) -> int:
        """Repair a restart between public trade finalization and tracker finalization."""

        async with self.database.session() as session:
            rows = (
                await session.execute(
                    select(SwingTracking.trade_id, TradeEvent.price)
                    .join(Trade, Trade.id == SwingTracking.trade_id)
                    .outerjoin(
                        TradeEvent,
                        (TradeEvent.trade_id == Trade.id) & (TradeEvent.action == "CLOSE"),
                    )
                    .where(
                        SwingTracking.guild_id == guild_id,
                        SwingTracking.tracking_state == "ACTIVE",
                        Trade.state == "CLOSED",
                        Trade.tracking_mode == SIMPLE_TRACKED_SWING,
                    )
                    .order_by(TradeEvent.created_at.desc())
                )
            ).all()
        seen: set[uuid.UUID] = set()
        for trade_id, price in rows:
            if trade_id in seen:
                continue
            seen.add(trade_id)
            await self.close_trade(
                trade_id,
                reference_price=price,
                reference_source="RESTART_RECONCILIATION",
            )
        return len(seen)

    async def poll(self, guild_id: int) -> int:
        await self.expire_contracts(guild_id)
        if self.provider is None or not self.calendar.is_market_open(datetime.now(UTC)):
            return 0
        return await self.refresh_active_prices(guild_id)

    async def refresh_active_prices(self, guild_id: int) -> int:
        """Best-effort forced refresh used by the Active View."""

        if self.provider is None:
            return 0
        async with self.database.session() as session:
            rows = (
                await session.execute(
                    select(SwingTracking, Trade)
                    .join(Trade, Trade.id == SwingTracking.trade_id)
                    .where(
                        SwingTracking.guild_id == guild_id,
                        SwingTracking.tracking_state == "ACTIVE",
                        Trade.tracking_mode == SIMPLE_TRACKED_SWING,
                    )
                    .order_by(Trade.public_trade_id)
                )
            ).all()
        requests = tuple(
            MarketPriceRequest(str(tracking.id), trade.ticker, tracking.option_ticker)
            for tracking, trade in rows
        )
        if not requests:
            return 0
        try:
            prices = await self.provider.fetch_prices(requests)
        except MarketDataProviderError as exc:
            await self._record_data_error([tracking.id for tracking, _ in rows], exc.code)
            if exc.code not in RECOVERABLE_ERRORS:
                raise
            return 0
        for failure in getattr(self.provider, "last_failures", ()):
            with suppress(AttributeError, ValueError):
                await self._record_data_error([uuid.UUID(failure.key)], failure.error_code)
        for price in prices:
            await self.process_price(uuid.UUID(price.key), price)
        return len(prices)

    async def process_price(self, tracking_id: uuid.UUID, market_price: MarketPrice) -> None:
        async with self.database.session() as session:
            tracking = await session.scalar(
                select(SwingTracking).where(SwingTracking.id == tracking_id).with_for_update()
            )
            if tracking is None:
                raise SwingTrackingError("SWING_TRACKING_NOT_FOUND")
            if tracking.tracking_state != "ACTIVE":
                return
            policy = self.policies.get(tracking.tracking_policy_version)
            if policy is None:
                raise SwingTrackingError("SWING_POLICY_VERSION_UNAVAILABLE")
            if market_price.price_source != tracking.price_source:
                raise SwingTrackingError("SWING_PRICE_SOURCE_CHANGED")
            last_quote = _aware(tracking.last_quote_at)
            if last_quote is not None and market_price.source_timestamp <= last_quote:
                return
            current_return = policy.return_pct(tracking.entry_price, market_price.price)
            tracking.current_price = market_price.price
            tracking.current_return_pct = current_return
            tracking.last_quote_at = market_price.source_timestamp
            tracking.last_session_date = market_price.source_timestamp.astimezone(ET).date()
            tracking.option_ticker = market_price.option_ticker
            tracking.consecutive_data_errors = 0
            tracking.last_error_code = None
            if market_price.price > tracking.highest_price:
                tracking.highest_price = market_price.price
                tracking.highest_return_pct = current_return
                tracking.highest_at = market_price.source_timestamp
            if market_price.price < tracking.lowest_price:
                tracking.lowest_price = market_price.price
                tracking.lowest_return_pct = current_return
                tracking.lowest_at = market_price.source_timestamp
            hit = {str(value) for value in tracking.tp_levels_hit}
            for rule in policy.crossed_tp_levels(current_return, hit):
                hit.add(rule.label)
                tracking.highest_tp_level = rule.label
                session.add(
                    self._event(
                        tracking,
                        "FIXED_TP_HIT",
                        f"FIXED_TP:{rule.label}",
                        market_price.source_timestamp,
                        market_price.received_at,
                        market_price.price,
                        current_return,
                        tp_return_pct=rule.return_pct,
                        public_notification=True,
                        public_card_type=rule.label,
                        public_price=policy.price_at_return(tracking.entry_price, rule.return_pct),
                        public_return_pct=Decimal(rule.return_pct),
                    )
                )
            tracking.tp_levels_hit = [rule.label for rule in policy.tp_levels if rule.label in hit]
            await self._update_daily_snapshot(session, tracking, market_price)
            tracking.version += 1
            await session.commit()

    async def close_trade(
        self,
        trade_id: uuid.UUID,
        *,
        reference_price: Decimal | None,
        reference_source: str,
    ) -> None:
        async with self.database.session() as session:
            tracking = await session.scalar(
                select(SwingTracking).where(SwingTracking.trade_id == trade_id).with_for_update()
            )
            if tracking is None:
                raise SwingTrackingError("SWING_TRACKING_NOT_FOUND")
            if tracking.tracking_state == "STOPPED":
                return
            now = utc_now()
            price = reference_price or tracking.current_price or tracking.entry_price
            current_return = self._policy(tracking).return_pct(tracking.entry_price, price)
            tracking.close_requested_at = now
            tracking.close_reference_price = price
            tracking.close_reference_return_pct = current_return
            tracking.close_reference_source = reference_source[:32]
            tracking.tracking_state = "STOPPED"
            tracking.tracking_end_reason = "MANUAL_SIGNAL_CLOSE"
            tracking.tracking_ended_at = now
            tracking.version += 1
            session.add(
                self._event(
                    tracking,
                    "MANUAL_SIGNAL_CLOSE",
                    "CLOSE",
                    tracking.last_quote_at or now,
                    now,
                    price,
                    current_return,
                )
            )
            await session.commit()

    async def expire_contracts(self, guild_id: int) -> int:
        current = datetime.now(ET)
        cutoff = (current.hour, current.minute) >= (16, 15)
        async with self.database.session() as session:
            rows = (
                await session.execute(
                    select(SwingTracking, Trade)
                    .join(Trade, Trade.id == SwingTracking.trade_id)
                    .where(
                        SwingTracking.guild_id == guild_id,
                        SwingTracking.tracking_state == "ACTIVE",
                        (
                            (Trade.expiry < current.date())
                            | ((Trade.expiry == current.date()) & cutoff)
                        ),
                    )
                    .with_for_update()
                )
            ).all()
            now = utc_now()
            for tracking, trade in rows:
                tracking.tracking_state = "STOPPED"
                tracking.tracking_end_reason = "OPTION_EXPIRED"
                tracking.tracking_ended_at = now
                tracking.version += 1
                trade.state = "CLOSED"
                trade.closed_at = now
                trade.final_return_pct = tracking.highest_return_pct
                trade.version += 1
                session.add(
                    self._event(
                        tracking,
                        "OPTION_EXPIRED",
                        "EXPIRED",
                        tracking.last_quote_at or now,
                        now,
                        tracking.current_price or tracking.entry_price,
                        tracking.current_return_pct or Decimal("0"),
                    )
                )
            await session.commit()
            return len(rows)

    async def active_positions(self, guild_id: int) -> tuple[SwingActivePosition, ...]:
        async with self.database.session() as session:
            rows = (
                await session.execute(
                    select(SwingTracking, Trade)
                    .join(Trade, Trade.id == SwingTracking.trade_id)
                    .where(
                        SwingTracking.guild_id == guild_id,
                        SwingTracking.tracking_state == "ACTIVE",
                        Trade.state == "ACTIVE",
                        Trade.tracking_mode == SIMPLE_TRACKED_SWING,
                    )
                    .order_by(Trade.public_trade_id)
                )
            ).all()
        now = datetime.now(UTC)
        return tuple(
            SwingActivePosition(
                public_trade_id=trade.public_trade_id,
                ticker=trade.ticker,
                expiry=trade.expiry,
                strike=trade.strike,
                option_side=trade.option_side,
                entry_price=tracking.entry_price,
                highest_tp_level=tracking.highest_tp_level,
                highest_tp_return_pct=self._tp_return_pct(tracking),
                highest_price=tracking.highest_price,
                highest_return_pct=tracking.highest_return_pct,
                current_price=tracking.current_price,
                current_return_pct=tracking.current_return_pct,
                last_quote_at=tracking.last_quote_at,
                stale=(
                    tracking.last_quote_at is None
                    or (now - _aware(tracking.last_quote_at)).total_seconds()
                    > self.policy.max_quote_age_seconds
                ),
                is_lotto=trade.is_lotto,
            )
            for tracking, trade in rows
        )

    async def active_legacy_positions(
        self, guild_id: int
    ) -> tuple[SwingActivePosition, ...]:
        """Render legacy Swing alongside tracked Swing without enrolling it in V2 tracking."""

        async with self.database.session() as session:
            trades = list(
                await session.scalars(
                    select(Trade)
                    .where(
                        Trade.guild_id == guild_id,
                        Trade.category == "SWING",
                        Trade.tracking_mode == LEGACY_SWING,
                        Trade.state.in_(("ACTIVE", "RUNNER")),
                        Trade.position_eighths > 0,
                    )
                    .order_by(Trade.public_trade_id)
                )
            )
            events_by_trade: dict[uuid.UUID, list[TradeEvent]] = {}
            snapshots: dict[uuid.UUID, MarketQuoteSnapshot] = {}
            for trade in trades:
                events_by_trade[trade.id] = list(
                    await session.scalars(
                        select(TradeEvent)
                        .where(TradeEvent.trade_id == trade.id)
                        .order_by(TradeEvent.created_at, TradeEvent.id)
                    )
                )
                snapshot = await session.scalar(
                    select(MarketQuoteSnapshot)
                    .where(MarketQuoteSnapshot.trade_id == trade.id)
                    .order_by(
                        MarketQuoteSnapshot.session_date.desc(),
                        MarketQuoteSnapshot.quote_time.desc(),
                    )
                    .limit(1)
                )
                if snapshot is not None:
                    snapshots[trade.id] = snapshot

        requests = tuple(
            MarketPriceRequest(
                str(trade.id),
                trade.ticker,
                trade.option_contract_code
                or massive_option_ticker(
                    trade.ticker,
                    trade.expiry,
                    trade.strike,
                    trade.option_side,
                ),
            )
            for trade in trades
        )
        fresh_prices: dict[uuid.UUID, MarketPrice] = {}
        if self.provider is not None and requests:
            try:
                fresh_prices = {
                    uuid.UUID(price.key): price
                    for price in await self.provider.fetch_prices(requests)
                }
            except (MarketDataProviderError, ValueError):
                logger.warning("event=legacy_swing_active_quote_unavailable")

        now = datetime.now(UTC)
        output: list[SwingActivePosition] = []
        for trade in trades:
            events = events_by_trade[trade.id]
            latest_cost = next(
                (
                    event.avg_cost_after
                    for event in reversed(events)
                    if event.avg_cost_after is not None
                ),
                None,
            )
            midpoint = (
                (trade.entry_low + trade.entry_high) / 2
                if trade.entry_low is not None and trade.entry_high is not None
                else trade.entry_low or trade.entry_high
            )
            entry_price = trade.avg_cost or latest_cost or midpoint
            if entry_price is None or entry_price <= 0:
                continue

            tp_events = [
                event
                for event in events
                if event.action in {"TP1", "TP2"} and event.pnl_pct is not None
            ]
            highest_tp = max(tp_events, key=lambda item: item.pnl_pct or Decimal("0"), default=None)
            current_price = None
            last_quote_at = None
            stale = True
            fresh = fresh_prices.get(trade.id)
            if fresh is not None:
                current_price = fresh.price
                last_quote_at = fresh.source_timestamp
                stale = (
                    now - _aware(fresh.source_timestamp)
                ).total_seconds() > self.policy.max_quote_age_seconds
            elif trade.id in snapshots:
                snapshot = snapshots[trade.id]
                current_price = snapshot.last_price
                last_quote_at = snapshot.quote_time

            current_return = (
                self.policy.return_pct(entry_price, current_price)
                if current_price is not None
                else None
            )
            observed_prices = [entry_price]
            observed_returns = [Decimal("0")]
            if current_price is not None and current_return is not None:
                observed_prices.append(current_price)
                observed_returns.append(current_return)
            observed_prices.extend(event.price for event in events if event.price is not None)
            observed_returns.extend(event.pnl_pct for event in events if event.pnl_pct is not None)
            output.append(
                SwingActivePosition(
                    public_trade_id=trade.public_trade_id,
                    ticker=trade.ticker,
                    expiry=trade.expiry,
                    strike=trade.strike,
                    option_side=trade.option_side,
                    entry_price=entry_price,
                    highest_tp_level=highest_tp.action if highest_tp is not None else None,
                    highest_tp_return_pct=(
                        int(highest_tp.pnl_pct) if highest_tp is not None else None
                    ),
                    highest_price=max(observed_prices),
                    highest_return_pct=max(observed_returns),
                    current_price=current_price,
                    current_return_pct=current_return,
                    last_quote_at=last_quote_at,
                    stale=stale,
                    is_lotto=trade.is_lotto,
                )
            )
        return tuple(output)

    async def next_public_event(self, guild_id: int) -> SwingEventClaim | None:
        async with self.database.session() as session:
            row = (
                await session.execute(
                    select(SwingTrackingEvent, Trade, GuildConfig)
                    .join(Trade, Trade.id == SwingTrackingEvent.trade_id)
                    .join(GuildConfig, GuildConfig.guild_id == SwingTrackingEvent.guild_id)
                    .where(
                        SwingTrackingEvent.guild_id == guild_id,
                        SwingTrackingEvent.public_notification.is_(True),
                        SwingTrackingEvent.published_at.is_(None),
                    )
                    .order_by(SwingTrackingEvent.created_at, SwingTrackingEvent.id)
                    .limit(1)
                )
            ).one_or_none()
            if row is None:
                return None
            event, trade, config = row
            if config.swing_channel_id is None or event.public_ref is None:
                raise SwingTrackingError("SWING_CHANNEL_NOT_CONFIGURED")
            return SwingEventClaim(
                event_id=event.id,
                channel_id=config.swing_channel_id,
                public_ref=event.public_ref,
                card=SwingTrackingCard(
                    public_trade_id=trade.public_trade_id,
                    card_type=event.public_card_type or "TP",
                    ticker=trade.ticker,
                    expiry=trade.expiry,
                    strike=trade.strike,
                    option_side=trade.option_side,
                    price=event.public_price or event.price,
                    return_pct=event.public_return_pct or event.return_pct,
                    highest_price=event.high_watermark_price,
                    highest_return_pct=event.high_watermark_return_pct,
                    is_lotto=trade.is_lotto,
                ),
            )

    async def mark_event_published(self, event_id: uuid.UUID, message_id: int) -> None:
        async with self.database.session() as session:
            event = await session.get(SwingTrackingEvent, event_id)
            if event is None:
                raise SwingTrackingError("SWING_EVENT_NOT_FOUND")
            if event.published_at is None:
                event.discord_message_id = message_id
                event.published_at = utc_now()
                await session.commit()

    async def _record_data_error(self, tracking_ids: Sequence[uuid.UUID], code: str) -> None:
        if not tracking_ids:
            return
        async with self.database.session() as session:
            rows = list(
                await session.scalars(
                    select(SwingTracking).where(
                        SwingTracking.id.in_(tracking_ids), SwingTracking.tracking_state == "ACTIVE"
                    )
                )
            )
            for tracking in rows:
                tracking.consecutive_data_errors += 1
                tracking.last_error_code = code[:64]
            await session.commit()

    async def _update_daily_snapshot(
        self, session, tracking: SwingTracking, price: MarketPrice
    ) -> None:
        session_date = price.source_timestamp.astimezone(ET).date()
        snapshot = await session.scalar(
            select(SwingDailySnapshot).where(
                SwingDailySnapshot.tracking_id == tracking.id,
                SwingDailySnapshot.session_date == session_date,
            )
        )
        if snapshot is None:
            snapshot = SwingDailySnapshot(
                guild_id=tracking.guild_id,
                tracking_id=tracking.id,
                trade_id=tracking.trade_id,
                session_date=session_date,
                closing_price=price.price,
                closing_return_pct=tracking.current_return_pct,
                highest_price=price.price,
                highest_return_pct=tracking.current_return_pct or Decimal("0"),
                lowest_price=price.price,
                lowest_return_pct=tracking.current_return_pct or Decimal("0"),
                tracking_state=tracking.tracking_state,
            )
            session.add(snapshot)
            return
        snapshot.closing_price = price.price
        snapshot.closing_return_pct = tracking.current_return_pct
        snapshot.highest_price = max(snapshot.highest_price, price.price)
        snapshot.lowest_price = min(snapshot.lowest_price, price.price)
        snapshot.highest_return_pct = self._policy(tracking).return_pct(
            tracking.entry_price, snapshot.highest_price
        )
        snapshot.lowest_return_pct = self._policy(tracking).return_pct(
            tracking.entry_price, snapshot.lowest_price
        )
        snapshot.tracking_state = tracking.tracking_state

    def _policy(self, tracking: SwingTracking) -> ShortTermTrackingPolicy:
        policy = self.policies.get(tracking.tracking_policy_version)
        if policy is None:
            raise SwingTrackingError("SWING_POLICY_VERSION_UNAVAILABLE")
        return policy

    def _tp_return_pct(self, tracking: SwingTracking) -> int | None:
        if tracking.highest_tp_level is None:
            return None
        return next(
            (
                rule.return_pct
                for rule in self._policy(tracking).tp_levels
                if rule.label == tracking.highest_tp_level
            ),
            None,
        )

    @staticmethod
    def _event(
        tracking: SwingTracking,
        event_type: str,
        event_key: str,
        market_time: datetime,
        received_at: datetime,
        price: Decimal,
        return_pct: Decimal,
        *,
        tp_return_pct: int | None = None,
        public_notification: bool = False,
        public_card_type: str | None = None,
        public_price: Decimal | None = None,
        public_return_pct: Decimal | None = None,
    ) -> SwingTrackingEvent:
        identifier = uuid.uuid4()
        return SwingTrackingEvent(
            id=identifier,
            guild_id=tracking.guild_id,
            tracking_id=tracking.id,
            trade_id=tracking.trade_id,
            event_key=event_key,
            event_type=event_type,
            tp_return_pct=tp_return_pct,
            source_market_timestamp=market_time,
            received_at=received_at,
            price=price,
            return_pct=return_pct,
            high_watermark_price=tracking.highest_price,
            high_watermark_return_pct=tracking.highest_return_pct,
            high_watermark_at=tracking.highest_at,
            low_watermark_price=tracking.lowest_price,
            low_watermark_return_pct=tracking.lowest_return_pct,
            tracking_policy_version=tracking.tracking_policy_version,
            price_source=tracking.price_source,
            public_notification=public_notification,
            public_card_type=public_card_type,
            public_price=public_price,
            public_return_pct=public_return_pct,
            public_ref=f"SWE-{identifier.hex[:12].upper()}" if public_notification else None,
        )


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
