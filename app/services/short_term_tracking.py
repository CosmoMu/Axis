from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    GuildConfig,
    ShortTermDailySnapshot,
    ShortTermTracking,
    ShortTermTrackingEvent,
    Trade,
    TradeEvent,
    TradePublication,
    utc_now,
)
from app.db.session import Database
from app.domain.public_cards import ShortTermTrackingCard
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
ACTIVE_STATES = {"ACTIVE", "OVERNIGHT_ACTIVE"}
RECOVERABLE_MARKET_DATA_ERRORS = {
    "LAST_TRADE_OUTLIER",
    "MASSIVE_PRICE_UNAVAILABLE",
    "MASSIVE_QUOTE_STALE",
    "OPTION_CONTRACT_NOT_FOUND",
}
REACTIVATABLE_PRICE_STOP_REASONS = {
    "INITIAL_TRACKING_PROTECTION",
    "TRAILING_TRACKING_PROTECTION",
    "OVERNIGHT_GAP_TRACKING_PROTECTION",
}

logger = logging.getLogger(__name__)


class ShortTermTrackingError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class TrackingEventClaim:
    event_id: uuid.UUID
    channel_id: int
    public_ref: str
    card: ShortTermTrackingCard


class MarketTrackingService:
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
        policies = {item.version: item for item in historical_policies}
        policies[policy.version] = policy
        if any(item.price_source != policy.price_source for item in policies.values()):
            raise ShortTermTrackingError("SHORT_TERM_PRICE_SOURCE_CHANGED")
        self.policies = policies
        self.provider = provider
        self.calendar = calendar or TradingCalendarService()

    @property
    def enabled(self) -> bool:
        return self.provider is not None

    async def register_trade(self, trade_id: uuid.UUID, entry_price: Decimal) -> None:
        if entry_price <= 0:
            raise ShortTermTrackingError("SHORT_TERM_ENTRY_PRICE_REQUIRED")
        async with self.database.session() as session:
            existing = await session.scalar(
                select(ShortTermTracking).where(ShortTermTracking.trade_id == trade_id)
            )
            if existing is not None:
                return
            trade = await session.get(Trade, trade_id)
            if trade is None or trade.category != "SHORT_TERM" or trade.mentor_id is not None:
                raise ShortTermTrackingError("SHORT_TERM_TRADE_INVALID")
            now = utc_now()
            protection_price, protection_return, protection_reason = self.policy.protection_for(
                entry_price, set()
            )
            tracking = ShortTermTracking(
                guild_id=trade.guild_id,
                trade_id=trade.id,
                option_ticker=(
                    trade.option_contract_code
                    or massive_option_ticker(
                        trade.ticker, trade.expiry, trade.strike, trade.option_side
                    )
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
                momentum_tp_events=[],
                tracking_protection_price=protection_price,
                tracking_protection_return_pct=Decimal(protection_return),
                tracking_protection_reason=protection_reason,
                tracking_state="ACTIVE",
                tracking_started_at=now,
                last_session_date=now.astimezone(ET).date(),
                tracking_policy_version=self.policy.version,
                price_source=self.policy.price_source,
            )
            session.add(tracking)
            await session.flush()
            session.add(
                self._event(
                    tracking,
                    event_type="ENTRY_PUBLISHED",
                    event_key="ENTRY",
                    market_time=now,
                    received_at=now,
                    price=entry_price,
                    return_pct=Decimal("0"),
                )
            )
            await session.commit()

    async def register_missing(self, guild_id: int) -> int:
        async with self.database.session() as session:
            rows = (
                await session.execute(
                    select(Trade.id, TradeEvent.price)
                    .join(
                        TradePublication,
                        TradePublication.trade_id == Trade.id,
                    )
                    .join(TradeEvent, TradeEvent.id == TradePublication.trade_event_id)
                    .outerjoin(ShortTermTracking, ShortTermTracking.trade_id == Trade.id)
                    .where(
                        Trade.guild_id == guild_id,
                        Trade.category == "SHORT_TERM",
                        Trade.mentor_id.is_(None),
                        TradePublication.status == "PUBLISHED",
                        ShortTermTracking.id.is_(None),
                        TradeEvent.price.is_not(None),
                    )
                )
            ).all()
        for trade_id, entry_price in rows:
            await self.register_trade(trade_id, entry_price)
        return len(rows)

    async def poll(self, guild_id: int) -> int:
        await self.reconcile_expiry_only(guild_id)
        await self.reconcile_contract_codes(guild_id)
        await self._expire_contracts(guild_id)
        if self.provider is None:
            return 0
        if not self.calendar.is_market_open(datetime.now(UTC)):
            return 0
        async with self.database.session() as session:
            rows = (
                await session.execute(
                    select(ShortTermTracking, Trade)
                    .join(Trade, Trade.id == ShortTermTracking.trade_id)
                    .where(
                        ShortTermTracking.guild_id == guild_id,
                        ShortTermTracking.tracking_state.in_(ACTIVE_STATES),
                    )
                    .order_by(Trade.public_trade_id)
                )
            ).all()
        requests = tuple(
            MarketPriceRequest(
                key=str(tracking.id),
                underlying=trade.ticker,
                option_ticker=tracking.option_ticker,
            )
            for tracking, trade in rows
        )
        try:
            prices = await self.provider.fetch_prices(requests)
        except MarketDataProviderError as exc:
            if exc.code not in RECOVERABLE_MARKET_DATA_ERRORS:
                raise
            await self._record_data_error(
                tuple(tracking.id for tracking, _trade in rows),
                exc.code,
            )
            return 0
        for failure in getattr(self.provider, "last_failures", ()):
            try:
                failed_tracking_id = uuid.UUID(failure.key)
            except (AttributeError, ValueError):
                continue
            await self._record_data_error((failed_tracking_id,), failure.error_code)
        processed = 0
        for market_price in prices:
            await self.process_price(uuid.UUID(market_price.key), market_price)
            processed += 1
        return processed

    async def reconcile_contract_codes(self, guild_id: int) -> int:
        async with self.database.session() as session:
            rows = (
                await session.execute(
                    select(ShortTermTracking, Trade)
                    .join(Trade, Trade.id == ShortTermTracking.trade_id)
                    .where(
                        ShortTermTracking.guild_id == guild_id,
                        ShortTermTracking.tracking_state.in_(ACTIVE_STATES),
                        Trade.option_contract_code.is_not(None),
                        ShortTermTracking.option_ticker != Trade.option_contract_code,
                    )
                    .with_for_update()
                )
            ).all()
            for tracking, trade in rows:
                previous = tracking.option_ticker
                tracking.option_ticker = trade.option_contract_code or previous
                tracking.consecutive_data_errors = 0
                tracking.last_error_code = None
                tracking.version += 1
                logger.info(
                    "event=short_term_contract_reconciled trade=%s previous=%s resolved=%s",
                    trade.public_trade_id,
                    previous,
                    tracking.option_ticker,
                )
            await session.commit()
            return len(rows)

    async def _record_data_error(
        self,
        tracking_ids: Sequence[uuid.UUID],
        error_code: str,
    ) -> None:
        if not tracking_ids:
            return
        async with self.database.session() as session:
            rows = list(
                await session.scalars(
                    select(ShortTermTracking)
                    .where(
                        ShortTermTracking.id.in_(tracking_ids),
                        ShortTermTracking.tracking_state.in_(ACTIVE_STATES),
                    )
                    .with_for_update()
                )
            )
            for tracking in rows:
                if tracking.consecutive_data_errors == 0:
                    logger.warning(
                        "event=short_term_quote_degraded tracking_id=%s "
                        "option_ticker=%s error_code=%s",
                        tracking.id,
                        tracking.option_ticker,
                        error_code,
                    )
                tracking.consecutive_data_errors += 1
                tracking.last_error_code = error_code[:64]
            await session.commit()

    async def expire_contracts(self, guild_id: int) -> None:
        await self._expire_contracts(guild_id)

    async def reconcile_expiry_only(self, guild_id: int) -> int:
        if self.policy.tracking_exit_mode != "EXPIRY_ONLY":
            return 0
        today = datetime.now(ET).date()
        async with self.database.session() as session:
            rows = (
                await session.execute(
                    select(ShortTermTracking, Trade)
                    .join(Trade, Trade.id == ShortTermTracking.trade_id)
                    .where(
                        ShortTermTracking.guild_id == guild_id,
                        ShortTermTracking.tracking_state == "STOPPED",
                        ShortTermTracking.tracking_end_reason.in_(
                            REACTIVATABLE_PRICE_STOP_REASONS
                        ),
                        Trade.expiry >= today,
                    )
                    .with_for_update()
                )
            ).all()
            if not rows:
                return 0
            tracking_ids = [tracking.id for tracking, _trade in rows]
            pending_stop_events = list(
                await session.scalars(
                    select(ShortTermTrackingEvent).where(
                        ShortTermTrackingEvent.tracking_id.in_(tracking_ids),
                        ShortTermTrackingEvent.event_type.in_(
                            ("TRACKING_STOPPED", "OVERNIGHT_GAP_STOP")
                        ),
                        ShortTermTrackingEvent.published_at.is_(None),
                    )
                )
            )
            for event in pending_stop_events:
                event.public_notification = False
            for tracking, trade in rows:
                previous_reason = tracking.tracking_end_reason
                tracking.tracking_state = (
                    "OVERNIGHT_ACTIVE"
                    if tracking.last_session_date is not None
                    and tracking.last_session_date < today
                    else "ACTIVE"
                )
                tracking.tracking_end_reason = None
                tracking.tracking_end_price = None
                tracking.tracking_end_return_pct = None
                tracking.tracking_ended_at = None
                policy = self.policies.get(tracking.tracking_policy_version, self.policy)
                sl_price, sl_return, sl_reason = policy.sl_alert_reference(
                    tracking.entry_price,
                    {str(value) for value in tracking.tp_levels_hit},
                )
                tracking.tracking_protection_price = sl_price
                tracking.tracking_protection_return_pct = Decimal(sl_return)
                tracking.tracking_protection_reason = f"{sl_reason}_PENDING"
                tracking.version += 1
                logger.info(
                    "event=short_term_reactivated_expiry_only trade=%s "
                    "previous_reason=%s expiry=%s",
                    trade.public_trade_id,
                    previous_reason,
                    trade.expiry,
                )
            await session.commit()
            return len(rows)

    async def process_price(self, tracking_id: uuid.UUID, market_price: MarketPrice) -> None:
        async with self.database.session() as session:
            tracking = await session.scalar(
                select(ShortTermTracking)
                .where(ShortTermTracking.id == tracking_id)
                .with_for_update()
            )
            if tracking is None:
                raise ShortTermTrackingError("SHORT_TERM_TRACKING_NOT_FOUND")
            if tracking.tracking_state not in ACTIVE_STATES:
                return
            policy = self.policies.get(tracking.tracking_policy_version)
            if policy is None:
                raise ShortTermTrackingError("SHORT_TERM_POLICY_VERSION_UNAVAILABLE")
            if market_price.price_source != tracking.price_source:
                raise ShortTermTrackingError("SHORT_TERM_PRICE_SOURCE_CHANGED")
            last_quote = _aware(tracking.last_quote_at)
            if last_quote is not None and market_price.source_timestamp <= last_quote:
                return

            previous_return = tracking.current_return_pct
            previous_high = tracking.highest_price
            current_return = policy.return_pct(tracking.entry_price, market_price.price)
            market_date = market_price.source_timestamp.astimezone(ET).date()
            new_session = (
                tracking.last_session_date is not None and market_date > tracking.last_session_date
            )

            tracking.current_price = market_price.price
            tracking.current_return_pct = current_return
            tracking.last_quote_at = market_price.source_timestamp
            tracking.last_session_date = market_date
            tracking.option_ticker = market_price.option_ticker
            if tracking.consecutive_data_errors:
                logger.info(
                    "event=short_term_quote_recovered tracking_id=%s "
                    "option_ticker=%s previous_error=%s error_count=%s",
                    tracking.id,
                    tracking.option_ticker,
                    tracking.last_error_code,
                    tracking.consecutive_data_errors,
                )
                tracking.consecutive_data_errors = 0
                tracking.last_error_code = None
            if market_price.price > tracking.highest_price:
                tracking.highest_price = market_price.price
                tracking.highest_return_pct = current_return
                tracking.highest_at = market_price.source_timestamp
                tracking.momentum_anchor_version += 1
            if market_price.price < tracking.lowest_price:
                tracking.lowest_price = market_price.price
                tracking.lowest_return_pct = current_return
                tracking.lowest_at = market_price.source_timestamp

            expiry_only = self.policy.tracking_exit_mode == "EXPIRY_ONLY"

            if new_session and tracking.tracking_state == "OVERNIGHT_ACTIVE":
                if not expiry_only and market_price.price <= tracking.tracking_protection_price:
                    self._stop(
                        session,
                        tracking,
                        market_price,
                        current_return,
                        reason="OVERNIGHT_GAP_TRACKING_PROTECTION",
                        event_type="OVERNIGHT_GAP_STOP",
                        public_notification=True,
                    )
                    await self._update_daily_snapshot(
                        session,
                        tracking,
                        market_price,
                        current_return,
                        market_date,
                    )
                    await session.commit()
                    return
                tracking.tracking_state = "ACTIVE"

            hit = set(str(value) for value in tracking.tp_levels_hit)
            crossed = policy.crossed_tp_levels(current_return, hit)
            for rule in crossed:
                hit.add(rule.label)
                tracking.momentum_anchor_version += 1
                session.add(
                    self._event(
                        tracking,
                        event_type="FIXED_TP_HIT",
                        event_key=f"FIXED_TP:{rule.label}",
                        market_time=market_price.source_timestamp,
                        received_at=market_price.received_at,
                        price=market_price.price,
                        return_pct=current_return,
                        tp_return_pct=rule.return_pct,
                        public_notification=True,
                        public_card_type=rule.label,
                        public_price=policy.price_at_return(
                            tracking.entry_price, rule.return_pct
                        ),
                        public_return_pct=Decimal(rule.return_pct),
                    )
                )
            tracking.tp_levels_hit = [
                rule.label for rule in policy.tp_levels if rule.label in hit
            ]
            if expiry_only:
                sl_price, sl_return, sl_reason = policy.sl_alert_reference(
                    tracking.entry_price,
                    hit,
                )
                same_sl_stage = tracking.tracking_protection_reason.startswith(sl_reason)
                sl_already_sent = (
                    same_sl_stage
                    and tracking.tracking_protection_reason == f"{sl_reason}_SENT"
                )
                tracking.tracking_protection_price = sl_price
                tracking.tracking_protection_return_pct = Decimal(sl_return)
                tracking.tracking_protection_reason = (
                    f"{sl_reason}_SENT" if sl_already_sent else f"{sl_reason}_PENDING"
                )
                if (
                    not sl_already_sent
                    and previous_return is not None
                    and previous_return > Decimal(sl_return)
                    and current_return <= Decimal(sl_return)
                ):
                    session.add(
                        self._event(
                            tracking,
                            event_type="SL_ALERT",
                            event_key=f"SL_ALERT:{sl_reason}",
                            market_time=market_price.source_timestamp,
                            received_at=market_price.received_at,
                            price=market_price.price,
                            return_pct=current_return,
                            public_notification=True,
                            public_card_type="SL",
                            public_price=sl_price,
                            public_return_pct=Decimal(sl_return),
                        )
                    )
                    tracking.tracking_protection_reason = f"{sl_reason}_SENT"
            new_protection, new_protection_return, new_protection_reason = (
                policy.protection_for(tracking.entry_price, hit)
            )
            if not expiry_only and new_protection > tracking.tracking_protection_price:
                tracking.tracking_protection_price = new_protection
                tracking.tracking_protection_return_pct = Decimal(new_protection_return)
                tracking.tracking_protection_reason = new_protection_reason
                session.add(
                    self._event(
                        tracking,
                        event_type="TRACKING_PROTECTION_MOVED",
                        event_key=f"TRACKING_PROTECTION:{new_protection_return}",
                        market_time=market_price.source_timestamp,
                        received_at=market_price.received_at,
                        price=market_price.price,
                        return_pct=current_return,
                    )
                )

            elapsed = max(
                0,
                int(
                    (
                        market_price.source_timestamp - _aware_required(tracking.highest_at)
                    ).total_seconds()
                ),
            )
            momentum = policy.momentum_drawdown(
                high_price=tracking.highest_price,
                high_return_pct=tracking.highest_return_pct,
                current_price=market_price.price,
                elapsed_seconds=elapsed,
            )
            cooldown = _aware(tracking.momentum_cooldown_until)
            if (
                momentum is not None
                and (cooldown is None or market_price.received_at >= cooldown)
                and tracking.momentum_anchor_version > tracking.momentum_last_event_anchor_version
                and market_price.price < previous_high
                and (
                    expiry_only
                    or market_price.price > tracking.tracking_protection_price
                )
            ):
                drawdown, _ = momentum
                event_id = uuid.uuid4()
                event_key = f"MOMENTUM:{event_id.hex}"
                session.add(
                    self._event(
                        tracking,
                        event_id=event_id,
                        event_type="FAST_MOMENTUM_REVERSAL",
                        event_key=event_key,
                        market_time=market_price.source_timestamp,
                        received_at=market_price.received_at,
                        price=market_price.price,
                        return_pct=current_return,
                        trigger_price=market_price.price,
                        trigger_return=current_return,
                        drawdown_pct=drawdown,
                        drawdown_seconds=elapsed,
                        public_notification=True,
                        public_card_type="TP",
                        public_price=tracking.highest_price,
                        public_return_pct=tracking.highest_return_pct,
                    )
                )
                tracking.momentum_last_event_anchor_version = tracking.momentum_anchor_version
                tracking.momentum_cooldown_until = (
                    market_price.received_at + policy.momentum_cooldown
                )
                tracking.momentum_tp_events = [
                    *tracking.momentum_tp_events,
                    {
                        "event_id": str(event_id),
                        "trigger_type": "FAST_MOMENTUM_REVERSAL",
                        "high_watermark_price": str(tracking.highest_price),
                        "trigger_market_price": str(market_price.price),
                        "drawdown_pct": str(drawdown),
                        "drawdown_duration_seconds": elapsed,
                        "triggered_at": market_price.source_timestamp.isoformat(),
                        "policy_version": policy.version,
                    },
                ]

            if not expiry_only and market_price.price <= tracking.tracking_protection_price:
                reason = (
                    "INITIAL_TRACKING_PROTECTION"
                    if not hit or tracking.tracking_protection_return_pct < 0
                    else "TRAILING_TRACKING_PROTECTION"
                )
                self._stop(
                    session,
                    tracking,
                    market_price,
                    current_return,
                    reason=reason,
                    event_type="TRACKING_STOPPED",
                    public_notification=True,
                )
            await self._update_daily_snapshot(
                session,
                tracking,
                market_price,
                current_return,
                market_date,
            )
            tracking.version += 1
            await session.commit()

    async def _update_daily_snapshot(
        self,
        session: AsyncSession,
        tracking: ShortTermTracking,
        market_price: MarketPrice,
        current_return: Decimal,
        market_date: date,
    ) -> None:
        snapshot = await session.scalar(
            select(ShortTermDailySnapshot).where(
                ShortTermDailySnapshot.tracking_id == tracking.id,
                ShortTermDailySnapshot.session_date == market_date,
            )
        )
        if snapshot is None:
            high_price = market_price.price
            high_return = current_return
            low_price = market_price.price
            low_return = current_return
            started_date = _aware_required(tracking.tracking_started_at).astimezone(ET).date()
            if started_date == market_date:
                high_price = max(high_price, tracking.entry_price)
                low_price = min(low_price, tracking.entry_price)
                high_return = self.policy.return_pct(tracking.entry_price, high_price)
                low_return = self.policy.return_pct(tracking.entry_price, low_price)
            if _aware_required(tracking.highest_at).astimezone(ET).date() == market_date:
                high_price = max(high_price, tracking.highest_price)
                high_return = self.policy.return_pct(tracking.entry_price, high_price)
            if _aware_required(tracking.lowest_at).astimezone(ET).date() == market_date:
                low_price = min(low_price, tracking.lowest_price)
                low_return = self.policy.return_pct(tracking.entry_price, low_price)
            snapshot = ShortTermDailySnapshot(
                guild_id=tracking.guild_id,
                tracking_id=tracking.id,
                trade_id=tracking.trade_id,
                session_date=market_date,
                closing_price=market_price.price,
                closing_return_pct=current_return,
                highest_price=high_price,
                highest_return_pct=high_return,
                lowest_price=low_price,
                lowest_return_pct=low_return,
                tracking_protection_price=tracking.tracking_protection_price,
                tracking_state=tracking.tracking_state,
                tracking_end_reason=tracking.tracking_end_reason,
            )
            session.add(snapshot)
            return
        snapshot.closing_price = market_price.price
        snapshot.closing_return_pct = current_return
        if market_price.price > snapshot.highest_price:
            snapshot.highest_price = market_price.price
            snapshot.highest_return_pct = current_return
        if market_price.price < snapshot.lowest_price:
            snapshot.lowest_price = market_price.price
            snapshot.lowest_return_pct = current_return
        snapshot.tracking_protection_price = tracking.tracking_protection_price
        snapshot.tracking_state = tracking.tracking_state
        snapshot.tracking_end_reason = tracking.tracking_end_reason

    async def next_public_event(self, guild_id: int) -> TrackingEventClaim | None:
        async with self.database.session() as session:
            row = (
                await session.execute(
                    select(ShortTermTrackingEvent, Trade, GuildConfig)
                    .join(Trade, Trade.id == ShortTermTrackingEvent.trade_id)
                    .join(GuildConfig, GuildConfig.guild_id == ShortTermTrackingEvent.guild_id)
                    .where(
                        ShortTermTrackingEvent.guild_id == guild_id,
                        ShortTermTrackingEvent.public_notification.is_(True),
                        ShortTermTrackingEvent.published_at.is_(None),
                    )
                    .order_by(ShortTermTrackingEvent.created_at, ShortTermTrackingEvent.id)
                    .limit(1)
                )
            ).one_or_none()
            if row is None:
                return None
            event, trade, config = row
            if config.short_term_channel_id is None or event.public_ref is None:
                raise ShortTermTrackingError("SHORT_TERM_CHANNEL_NOT_CONFIGURED")
            return TrackingEventClaim(
                event_id=event.id,
                channel_id=config.short_term_channel_id,
                public_ref=event.public_ref,
                card=ShortTermTrackingCard(
                    public_trade_id=trade.public_trade_id,
                    card_type=event.public_card_type or "TP",
                    ticker=trade.ticker,
                    expiry=trade.expiry,
                    strike=trade.strike,
                    option_side=trade.option_side,
                    price=event.public_price or event.price,
                    return_pct=event.public_return_pct or event.return_pct,
                    highest_return_pct=(
                        event.high_watermark_return_pct
                        if event.public_card_type in {"STOP_TRACKING", "EXPIRED"}
                        else None
                    ),
                    is_lotto=trade.is_lotto,
                ),
            )

    async def mark_event_published(self, event_id: uuid.UUID, message_id: int) -> None:
        async with self.database.session() as session:
            event = await session.scalar(
                select(ShortTermTrackingEvent)
                .where(ShortTermTrackingEvent.id == event_id)
                .with_for_update()
            )
            if event is None:
                raise ShortTermTrackingError("SHORT_TERM_EVENT_NOT_FOUND")
            if event.published_at is None:
                event.discord_message_id = message_id
                event.published_at = utc_now()
                await session.commit()

    async def _expire_contracts(self, guild_id: int) -> None:
        current = datetime.now(ET)
        today = current.date()
        expiry_cutoff_reached = (current.hour, current.minute) >= (16, 15)
        async with self.database.session() as session:
            rows = (
                await session.execute(
                    select(ShortTermTracking, Trade)
                    .join(Trade, Trade.id == ShortTermTracking.trade_id)
                    .where(
                        ShortTermTracking.guild_id == guild_id,
                        ShortTermTracking.tracking_state.in_(ACTIVE_STATES),
                        (
                            (Trade.expiry < today)
                            | ((Trade.expiry == today) & expiry_cutoff_reached)
                        ),
                    )
                )
            ).all()
            for tracking, _trade in rows:
                now = utc_now()
                tracking.tracking_state = "STOPPED"
                tracking.tracking_end_reason = "EXPIRED_CONTRACT"
                tracking.tracking_end_price = tracking.current_price
                tracking.tracking_end_return_pct = tracking.current_return_pct
                tracking.tracking_ended_at = now
                tracking.version += 1
                session.add(
                    self._event(
                        tracking,
                        event_type="TRACKING_STOPPED",
                        event_key="STOP:EXPIRED_CONTRACT",
                        market_time=tracking.last_quote_at or now,
                        received_at=now,
                        price=tracking.current_price or tracking.entry_price,
                        return_pct=tracking.current_return_pct or Decimal("0"),
                        public_notification=True,
                        public_card_type="EXPIRED",
                        public_price=tracking.current_price or tracking.entry_price,
                        public_return_pct=tracking.current_return_pct or Decimal("0"),
                    )
                )
            await session.commit()

    def _stop(
        self,
        session: AsyncSession,
        tracking: ShortTermTracking,
        market_price: MarketPrice,
        current_return: Decimal,
        *,
        reason: str,
        event_type: str,
        public_notification: bool,
    ) -> None:
        tracking.tracking_state = "STOPPED"
        tracking.tracking_end_reason = reason
        tracking.tracking_end_price = market_price.price
        tracking.tracking_end_return_pct = current_return
        tracking.tracking_ended_at = market_price.received_at
        session.add(
            self._event(
                tracking,
                event_type=event_type,
                event_key=f"STOP:{reason}",
                market_time=market_price.source_timestamp,
                received_at=market_price.received_at,
                price=market_price.price,
                return_pct=current_return,
                public_notification=public_notification,
                public_card_type="STOP_TRACKING" if public_notification else None,
                public_price=market_price.price if public_notification else None,
                public_return_pct=current_return if public_notification else None,
            )
        )

    def _event(
        self,
        tracking: ShortTermTracking,
        *,
        event_type: str,
        event_key: str,
        market_time: datetime,
        received_at: datetime,
        price: Decimal,
        return_pct: Decimal,
        event_id: uuid.UUID | None = None,
        tp_return_pct: int | None = None,
        trigger_price: Decimal | None = None,
        trigger_return: Decimal | None = None,
        drawdown_pct: Decimal | None = None,
        drawdown_seconds: int | None = None,
        public_notification: bool = False,
        public_card_type: str | None = None,
        public_price: Decimal | None = None,
        public_return_pct: Decimal | None = None,
    ) -> ShortTermTrackingEvent:
        identifier = event_id or uuid.uuid4()
        return ShortTermTrackingEvent(
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
            tracking_protection_price=tracking.tracking_protection_price,
            trigger_market_price=trigger_price,
            trigger_market_return_pct=trigger_return,
            drawdown_pct=drawdown_pct,
            drawdown_duration_seconds=drawdown_seconds,
            tracking_policy_version=tracking.tracking_policy_version,
            price_source=tracking.price_source,
            public_notification=public_notification,
            public_card_type=public_card_type,
            public_price=public_price,
            public_return_pct=public_return_pct,
            public_ref=f"STE-{identifier.hex[:12].upper()}" if public_notification else None,
        )


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _aware_required(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
