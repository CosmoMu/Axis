from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AuditLog,
    GuildConfig,
    SwingTracking,
    Trade,
    TradeDraft,
    TradeEvent,
    TradePublication,
    utc_now,
)
from app.db.session import Database
from app.domain.enums import (
    ActionStage,
    DraftStatus,
    PublicationStatus,
    TradeAction,
    TradeCategory,
    TradeState,
)
from app.domain.public_cards import (
    ActivePublicTrade,
    PublicTradeCard,
    ShortTermEntryCard,
    SwingTrackedEntryCard,
    SwingTrackingCard,
)
from app.services.card_review import _plan_decimal, _public_thesis
from app.services.option_contracts import ContractValidationStatus, OptionContractResolver
from app.services.short_term_policy import ShortTermTrackingPolicy
from app.services.swing_tracking import SIMPLE_TRACKED_SWING

ACTIVE_CUSTOM_IDS = {
    TradeCategory.SWING.value: "axis:active:swing:v1",
    TradeCategory.LEAPS.value: "axis:active:leaps:v1",
}
PUBLIC_ID_PREFIXES = {
    TradeCategory.SHORT_TERM.value: "ST",
    TradeCategory.SWING.value: "SW",
    TradeCategory.LEAPS.value: "LP",
}
RETRY_AFTER = timedelta(seconds=60)


class PublicationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class PublicationConflictError(PublicationError):
    pass


class PublicationValidationError(PublicationError):
    pass


@dataclass(frozen=True, slots=True)
class PublicationClaim:
    publication_id: uuid.UUID
    draft_id: uuid.UUID
    claim_token: str | None
    should_publish: bool
    already_published: bool
    channel_id: int
    public_ref: str
    card: PublicTradeCard | ShortTermEntryCard | SwingTrackedEntryCard | SwingTrackingCard | None
    message_id: int | None


@dataclass(frozen=True, slots=True)
class PublicationResult:
    publication_id: uuid.UUID
    draft_id: uuid.UUID
    trade_id: uuid.UUID
    trade_event_id: uuid.UUID
    message_id: int
    public_trade_id: str


@dataclass(frozen=True, slots=True)
class LegacyComponentTarget:
    publication_id: uuid.UUID
    channel_id: int
    message_id: int


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _payload_hash(
    card: PublicTradeCard | ShortTermEntryCard | SwingTrackedEntryCard | SwingTrackingCard,
) -> str:
    payload = {
        key: (item.isoformat() if hasattr(item, "isoformat") else str(item))
        for key, item in asdict(card).items()
        if item is not None
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class TradePublicationService:
    def __init__(
        self,
        database: Database,
        contract_resolver: OptionContractResolver | None = None,
    ) -> None:
        self.database = database
        self.contract_resolver = contract_resolver

    async def next_publishable(self, guild_id: int) -> uuid.UUID | None:
        cutoff = utc_now() - RETRY_AFTER
        async with self.database.session() as session:
            draft_id = await session.scalar(
                select(TradeDraft.id)
                .outerjoin(TradePublication, TradePublication.draft_id == TradeDraft.id)
                .where(
                    TradeDraft.guild_id == guild_id,
                    or_(
                        and_(
                            TradeDraft.status == DraftStatus.READY.value,
                            or_(
                                TradePublication.id.is_(None),
                                and_(
                                    TradePublication.status == PublicationStatus.PENDING.value,
                                    or_(
                                        TradePublication.claimed_at.is_(None),
                                        TradePublication.claimed_at <= cutoff,
                                    ),
                                ),
                            ),
                        ),
                        and_(
                            TradeDraft.status == DraftStatus.PUBLISH_FAILED.value,
                            TradePublication.status == PublicationStatus.FAILED.value,
                            or_(
                                TradePublication.claimed_at.is_(None),
                                TradePublication.claimed_at <= cutoff,
                            ),
                        ),
                    ),
                )
                .order_by(TradeDraft.updated_at, TradeDraft.id)
                .limit(1)
            )
            return draft_id

    async def claim(
        self,
        draft_id: uuid.UUID,
        *,
        actor_user_id: int | None = None,
        interaction_id: int | None = None,
    ) -> PublicationClaim:
        async with self.database.session() as session:
            draft = await session.scalar(
                select(TradeDraft).where(TradeDraft.id == draft_id).with_for_update()
            )
            if draft is None:
                raise PublicationValidationError("DRAFT_NOT_FOUND")
            if draft.reviewed_by is None:
                raise PublicationValidationError("APPROVER_REQUIRED")
            publication = await session.scalar(
                select(TradePublication)
                .where(TradePublication.draft_id == draft.id)
                .with_for_update()
            )
            if publication is not None and publication.status == PublicationStatus.PUBLISHED.value:
                return self._existing_claim(publication, draft)
            if draft.status not in {
                DraftStatus.READY.value,
                DraftStatus.PUBLISH_FAILED.value,
            }:
                raise PublicationValidationError("DRAFT_NOT_READY")
            if (
                self.contract_resolver is not None
                and draft.intent == "NEW_TRADE"
                and (
                    draft.expiry is None
                    or draft.contract_validation_status != ContractValidationStatus.VALID.value
                    or not draft.option_contract_code
                )
            ):
                raise PublicationValidationError("CONTRACT_NOT_VALIDATED")

            now = utc_now()
            if (
                publication is not None
                and publication.status == PublicationStatus.PENDING.value
                and publication.claimed_at is not None
                and _aware(publication.claimed_at) > now - RETRY_AFTER
            ):
                return self._existing_claim(publication, draft)

            config = await session.scalar(
                select(GuildConfig).where(GuildConfig.guild_id == draft.guild_id).with_for_update()
            )
            if config is None:
                raise PublicationValidationError("GUILD_CONFIG_NOT_FOUND")
            trade = await self._resolve_trade(session, config, draft, publication)
            trade.is_lotto = draft.is_lotto
            pending_for_trade = await session.scalar(
                select(TradePublication.id).where(
                    TradePublication.trade_id == trade.id,
                    TradePublication.draft_id != draft.id,
                    TradePublication.status == PublicationStatus.PENDING.value,
                )
            )
            if pending_for_trade is not None:
                raise PublicationConflictError("TRADE_PUBLICATION_PENDING")

            category = trade.category
            channel_id = self._channel_id(config, category)
            card = await self._public_card(session, draft, trade)
            token = uuid.uuid4().hex
            if publication is None:
                publication = TradePublication(
                    guild_id=draft.guild_id,
                    trade_id=trade.id,
                    draft_id=draft.id,
                    message_type="SIGNAL_CARD",
                    channel_id=channel_id,
                    public_ref=(
                        f"P-{uuid.uuid4().hex[:12].upper()}"
                        if category == TradeCategory.SHORT_TERM.value
                        else await self._next_public_ref(session, config)
                    ),
                    custom_id=ACTIVE_CUSTOM_IDS.get(category),
                    payload_hash=_payload_hash(card),
                    status=PublicationStatus.PENDING.value,
                    attempt_count=1,
                    claim_token=token,
                    claimed_at=now,
                )
                session.add(publication)
            else:
                publication.trade_id = trade.id
                publication.channel_id = channel_id
                publication.custom_id = ACTIVE_CUSTOM_IDS.get(category)
                if category != TradeCategory.SHORT_TERM.value and not re.fullmatch(
                    r"P-\d{4,6}", publication.public_ref or ""
                ):
                    publication.public_ref = await self._next_public_ref(session, config)
                publication.payload_hash = _payload_hash(card)
                publication.status = PublicationStatus.PENDING.value
                publication.attempt_count += 1
                publication.claim_token = token
                publication.claimed_at = now
                publication.last_error_code = None
            draft.status = DraftStatus.READY.value
            await session.flush()
            await self._audit(
                session,
                draft=draft,
                actor_user_id=actor_user_id,
                interaction_id=interaction_id,
                action_type="TRADE_PUBLICATION_CLAIMED",
                after={
                    "publication_id": str(publication.id),
                    "attempt_count": publication.attempt_count,
                    "channel_id": channel_id,
                },
            )
            await session.commit()
            return PublicationClaim(
                publication_id=publication.id,
                draft_id=draft.id,
                claim_token=token,
                should_publish=True,
                already_published=False,
                channel_id=channel_id,
                public_ref=publication.public_ref or "",
                card=card,
                message_id=None,
            )

    async def mark_failed(
        self,
        publication_id: uuid.UUID,
        *,
        claim_token: str,
        error_code: str,
    ) -> None:
        async with self.database.session() as session:
            publication = await session.scalar(
                select(TradePublication)
                .where(TradePublication.id == publication_id)
                .with_for_update()
            )
            if publication is None:
                raise PublicationValidationError("PUBLICATION_NOT_FOUND")
            if publication.status == PublicationStatus.PUBLISHED.value:
                return
            if publication.claim_token != claim_token:
                raise PublicationConflictError("PUBLICATION_CLAIM_CONFLICT")
            draft = await session.scalar(
                select(TradeDraft).where(TradeDraft.id == publication.draft_id).with_for_update()
            )
            if draft is None:
                raise PublicationValidationError("DRAFT_NOT_FOUND")
            publication.status = PublicationStatus.FAILED.value
            publication.last_error_code = error_code[:64]
            draft.status = DraftStatus.PUBLISH_FAILED.value
            draft.version += 1
            await self._audit(
                session,
                draft=draft,
                actor_user_id=None,
                interaction_id=None,
                action_type="TRADE_PUBLICATION_FAILED",
                after={"publication_id": str(publication.id), "error_code": error_code[:64]},
            )
            await session.commit()

    async def finalize(
        self,
        publication_id: uuid.UUID,
        *,
        claim_token: str,
        message_id: int,
    ) -> PublicationResult:
        async with self.database.session() as session:
            publication = await session.scalar(
                select(TradePublication)
                .where(TradePublication.id == publication_id)
                .with_for_update()
            )
            if publication is None:
                raise PublicationValidationError("PUBLICATION_NOT_FOUND")
            if publication.status == PublicationStatus.PUBLISHED.value:
                return await self._published_result(session, publication)
            if publication.claim_token != claim_token:
                raise PublicationConflictError("PUBLICATION_CLAIM_CONFLICT")
            draft = await session.scalar(
                select(TradeDraft).where(TradeDraft.id == publication.draft_id).with_for_update()
            )
            trade = await session.scalar(
                select(Trade).where(Trade.id == publication.trade_id).with_for_update()
            )
            if draft is None or trade is None:
                raise PublicationValidationError("PUBLICATION_DATA_MISSING")
            if draft.status not in {
                DraftStatus.READY.value,
                DraftStatus.PUBLISH_FAILED.value,
            }:
                raise PublicationValidationError("DRAFT_NOT_READY")

            tracked = trade.category == TradeCategory.SHORT_TERM.value or (
                trade.category == TradeCategory.SWING.value
                and trade.tracking_mode == SIMPLE_TRACKED_SWING
            )
            before_position = trade.position_eighths
            after_position = 0 if tracked else draft.position_after_eighths
            if after_position is None:
                raise PublicationValidationError("POSITION_AFTER_REQUIRED")
            position_delta = after_position - before_position
            if (
                not tracked
                and draft.position_delta_eighths is not None
                and draft.position_delta_eighths != position_delta
            ):
                raise PublicationValidationError("POSITION_TRANSITION_MISMATCH")

            avg_cost_after = self._average_cost_after(
                trade,
                draft,
                before_position=before_position,
                after_position=after_position,
            )
            event = TradeEvent(
                trade_id=trade.id,
                action=draft.action,
                action_stage=draft.action_stage or ActionStage.NONE.value,
                price=self._event_price(draft),
                position_delta_eighths=position_delta,
                position_after_eighths=after_position,
                avg_cost_after=avg_cost_after,
                pnl_pct=draft.current_pnl_pct,
                sl_before=trade.sl,
                sl_after=draft.sl if draft.sl is not None else trade.sl,
                tp1_after=draft.tp1 if draft.tp1 is not None else trade.tp1,
                tp2_after=draft.tp2 if draft.tp2 is not None else trade.tp2,
                source_message_id=draft.source_message_id,
                draft_id=draft.id,
                approved_by=draft.reviewed_by,
                published_message_id=message_id,
            )
            session.add(event)
            self._apply_trade_update(
                trade,
                draft,
                after_position,
                avg_cost_after=avg_cost_after,
            )
            if (
                trade.tracking_mode == SIMPLE_TRACKED_SWING
                and draft.action == TradeAction.CLOSE.value
            ):
                tracking = await session.scalar(
                    select(SwingTracking)
                    .where(SwingTracking.trade_id == trade.id)
                    .with_for_update()
                )
                if tracking is None:
                    raise PublicationValidationError("SWING_TRACKING_NOT_FOUND")
                trade.final_return_pct = tracking.highest_return_pct
            await session.flush()

            publication.trade_event_id = event.id
            publication.message_id = message_id
            publication.status = PublicationStatus.PUBLISHED.value
            publication.last_error_code = None
            publication.published_at = utc_now()
            draft.status = DraftStatus.PUBLISHED.value
            draft.version += 1
            await self._audit(
                session,
                draft=draft,
                actor_user_id=None,
                interaction_id=None,
                action_type="TRADE_PUBLISHED",
                after={
                    "publication_id": str(publication.id),
                    "trade_id": str(trade.id),
                    "trade_event_id": str(event.id),
                    "message_id": message_id,
                },
            )
            await session.commit()
            return PublicationResult(
                publication_id=publication.id,
                draft_id=draft.id,
                trade_id=trade.id,
                trade_event_id=event.id,
                message_id=message_id,
                public_trade_id=trade.public_trade_id,
            )

    async def current_orders(self, guild_id: int, category: str) -> list[ActivePublicTrade]:
        if category not in PUBLIC_ID_PREFIXES:
            raise PublicationValidationError("CATEGORY_INVALID")
        async with self.database.session() as session:
            trades = (
                await session.scalars(
                    select(Trade)
                    .where(
                        Trade.guild_id == guild_id,
                        Trade.category == category,
                        Trade.state.in_([TradeState.ACTIVE.value, TradeState.RUNNER.value]),
                        Trade.position_eighths > 0,
                    )
                    .order_by(Trade.opened_at, Trade.public_trade_id)
                    .limit(25)
                )
            ).all()
            output = []
            for trade in trades:
                latest_cost = await session.scalar(
                    select(TradeEvent.avg_cost_after)
                    .where(
                        TradeEvent.trade_id == trade.id,
                        TradeEvent.avg_cost_after.is_not(None),
                    )
                    .order_by(TradeEvent.created_at.desc(), TradeEvent.id.desc())
                    .limit(1)
                )
                if trade.entry_low is not None and trade.entry_high is not None:
                    entry_cost = (trade.entry_low + trade.entry_high) / 2
                else:
                    entry_cost = trade.entry_low or trade.entry_high
                output.append(
                    ActivePublicTrade(
                        public_trade_id=trade.public_trade_id,
                        ticker=trade.ticker,
                        expiry=trade.expiry,
                        strike=trade.strike,
                        option_side=trade.option_side,
                        last_public_action=trade.last_public_action or TradeAction.ENTRY.value,
                        position_eighths=trade.position_eighths,
                        avg_cost=trade.avg_cost or latest_cost or entry_cost,
                        is_lotto=trade.is_lotto,
                    )
                )
        return output

    async def legacy_short_term_components(self, guild_id: int) -> list[LegacyComponentTarget]:
        async with self.database.session() as session:
            rows = (
                await session.execute(
                    select(
                        TradePublication.id,
                        TradePublication.channel_id,
                        TradePublication.message_id,
                    )
                    .join(Trade, Trade.id == TradePublication.trade_id)
                    .where(
                        Trade.guild_id == guild_id,
                        Trade.category == TradeCategory.SHORT_TERM.value,
                        TradePublication.status == PublicationStatus.PUBLISHED.value,
                        TradePublication.custom_id == "axis:active:short_term:v1",
                        TradePublication.message_id.is_not(None),
                    )
                )
            ).all()
        return [
            LegacyComponentTarget(
                publication_id=publication_id,
                channel_id=channel_id,
                message_id=message_id,
            )
            for publication_id, channel_id, message_id in rows
            if message_id is not None
        ]

    async def mark_legacy_component_removed(self, publication_id: uuid.UUID) -> None:
        async with self.database.session() as session:
            publication = await session.scalar(
                select(TradePublication)
                .where(TradePublication.id == publication_id)
                .with_for_update()
            )
            if publication is None:
                raise PublicationValidationError("PUBLICATION_NOT_FOUND")
            if publication.custom_id == "axis:active:short_term:v1":
                publication.custom_id = None
                await session.commit()

    async def _resolve_trade(
        self,
        session: AsyncSession,
        config: GuildConfig,
        draft: TradeDraft,
        publication: TradePublication | None,
    ) -> Trade:
        if publication is not None and publication.trade_id is not None:
            trade = await session.get(Trade, publication.trade_id)
            if trade is None:
                raise PublicationValidationError("TRADE_NOT_FOUND")
            return trade
        if draft.intent == "UPDATE_TRADE":
            if draft.matched_trade_id is None:
                raise PublicationValidationError("MATCHED_TRADE_REQUIRED")
            trade = await session.scalar(
                select(Trade).where(Trade.id == draft.matched_trade_id).with_for_update()
            )
            simple_swing = draft.parse_payload.get("_swing_mode") == SIMPLE_TRACKED_SWING
            if (
                trade is None
                or trade.guild_id != draft.guild_id
                or trade.category == TradeCategory.SHORT_TERM.value
                or trade.state not in {TradeState.ACTIVE.value, TradeState.RUNNER.value}
                or (
                    simple_swing
                    and (
                        trade.category != TradeCategory.SWING.value
                        or trade.tracking_mode != SIMPLE_TRACKED_SWING
                        or draft.action != TradeAction.CLOSE.value
                    )
                )
            ):
                raise PublicationValidationError("TRADE_UNAVAILABLE")
            return trade
        if draft.intent != "NEW_TRADE":
            raise PublicationValidationError("INTENT_INVALID")
        category = draft.selected_category or ""
        simple_swing = (
            category == TradeCategory.SWING.value
            and draft.parse_payload.get("_swing_mode") == SIMPLE_TRACKED_SWING
        )
        required = (
            draft.selected_category,
            draft.ticker,
            draft.expiry,
            draft.strike,
            draft.option_side,
        )
        if category != TradeCategory.SHORT_TERM.value and not simple_swing:
            required = (*required, draft.mentor_id)
        if any(value is None for value in required):
            raise PublicationValidationError("DRAFT_INCOMPLETE")
        if category == TradeCategory.SHORT_TERM.value and draft.intent != "NEW_TRADE":
            raise PublicationValidationError("SHORT_TERM_NEW_TRADE_REQUIRED")
        public_trade_id = await self._next_public_trade_id(session, config, category)
        trade = Trade(
            guild_id=draft.guild_id,
            public_trade_id=public_trade_id,
            category=category,
            tracking_mode=SIMPLE_TRACKED_SWING if simple_swing else None,
            mentor_id=(
                None
                if category == TradeCategory.SHORT_TERM.value or simple_swing
                else draft.mentor_id
            ),
            ticker=draft.ticker or "",
            expiry=draft.expiry,
            strike=draft.strike,
            option_side=draft.option_side or "",
            option_contract_code=(
                draft.option_contract_code
                if category == TradeCategory.SHORT_TERM.value or simple_swing
                else None
            ),
            state=TradeState.DRAFT.value,
            position_eighths=0,
            max_position_eighths=0,
            entry_low=draft.entry_low,
            entry_high=draft.entry_high,
            avg_cost=draft.avg_cost,
            sl=draft.sl,
            tp1=draft.tp1,
            tp2=draft.tp2,
            is_lotto=draft.is_lotto,
        )
        session.add(trade)
        await session.flush()
        draft.matched_trade_id = trade.id
        return trade

    @staticmethod
    async def _next_public_trade_id(
        session: AsyncSession, config: GuildConfig, category: str
    ) -> str:
        if category not in PUBLIC_ID_PREFIXES:
            raise PublicationValidationError("CATEGORY_INVALID")
        await session.refresh(config, with_for_update=True)
        prefix = PUBLIC_ID_PREFIXES[category]
        identifiers = (
            await session.scalars(
                select(Trade.public_trade_id).where(
                    Trade.guild_id == config.guild_id,
                    Trade.public_trade_id.like(f"{prefix}-%"),
                )
            )
        ).all()
        numbers = []
        for identifier in identifiers:
            try:
                numbers.append(int(identifier.removeprefix(f"{prefix}-")))
            except ValueError:
                continue
        return f"{prefix}-{max(numbers, default=0) + 1:04d}"

    @staticmethod
    async def _next_public_ref(session: AsyncSession, config: GuildConfig) -> str:
        await session.refresh(config, with_for_update=True)
        count = await session.scalar(
            select(func.count())
            .select_from(TradePublication)
            .where(TradePublication.guild_id == config.guild_id)
        )
        return f"P-{int(count or 0) + 1:04d}"

    @staticmethod
    def _channel_id(config: GuildConfig, category: str) -> int:
        channel_id = {
            TradeCategory.SHORT_TERM.value: config.short_term_channel_id,
            TradeCategory.SWING.value: config.swing_channel_id,
            TradeCategory.LEAPS.value: config.leaps_channel_id,
        }.get(category)
        if channel_id is None:
            raise PublicationValidationError("PUBLIC_CHANNEL_NOT_CONFIGURED")
        return channel_id

    @staticmethod
    async def _public_card(
        session: AsyncSession, draft: TradeDraft, trade: Trade
    ) -> PublicTradeCard | ShortTermEntryCard | SwingTrackedEntryCard | SwingTrackingCard:
        if trade.category == TradeCategory.SHORT_TERM.value:
            entry_price = TradePublicationService._event_price(draft)
            if entry_price is None or entry_price <= 0:
                raise PublicationValidationError("SHORT_TERM_ENTRY_PRICE_REQUIRED")
            return ShortTermEntryCard(
                public_trade_id=trade.public_trade_id,
                ticker=trade.ticker,
                expiry=trade.expiry,
                strike=trade.strike,
                option_side=trade.option_side,
                entry_price=entry_price,
                is_lotto=trade.is_lotto,
            )
        if (
            trade.category == TradeCategory.SWING.value
            and trade.tracking_mode == SIMPLE_TRACKED_SWING
        ):
            if draft.action == TradeAction.ENTRY.value:
                entry_price = TradePublicationService._event_price(draft)
                if entry_price is None or entry_price <= 0:
                    raise PublicationValidationError("SWING_ENTRY_PRICE_REQUIRED")
                return SwingTrackedEntryCard(
                    public_trade_id=trade.public_trade_id,
                    ticker=trade.ticker,
                    expiry=trade.expiry,
                    strike=trade.strike,
                    option_side=trade.option_side,
                    entry_price=entry_price,
                    is_lotto=trade.is_lotto,
                )
            if draft.action != TradeAction.CLOSE.value:
                raise PublicationValidationError("SIMPLE_SWING_ACTION_INVALID")
            tracking = await session.scalar(
                select(SwingTracking).where(SwingTracking.trade_id == trade.id)
            )
            if tracking is None:
                raise PublicationValidationError("SWING_TRACKING_NOT_FOUND")
            reference = draft.action_price or tracking.current_price or tracking.entry_price
            reference_return = ShortTermTrackingPolicy.return_pct(tracking.entry_price, reference)
            return SwingTrackingCard(
                public_trade_id=trade.public_trade_id,
                card_type="CLOSE",
                ticker=trade.ticker,
                expiry=trade.expiry,
                strike=trade.strike,
                option_side=trade.option_side,
                price=reference,
                return_pct=reference_return,
                highest_price=tracking.highest_price,
                highest_return_pct=tracking.highest_return_pct,
                entry_price=tracking.entry_price,
                is_lotto=trade.is_lotto,
            )
        return PublicTradeCard(
            public_trade_id=trade.public_trade_id,
            category=trade.category,
            action=draft.action,
            action_stage=draft.action_stage,
            ticker=draft.ticker or trade.ticker,
            expiry=draft.expiry or trade.expiry,
            strike=draft.strike or trade.strike,
            option_side=draft.option_side or trade.option_side,
            entry_low=draft.entry_low,
            entry_high=draft.entry_high,
            action_price=draft.action_price,
            avg_cost=draft.avg_cost,
            sl=draft.sl,
            tp1=draft.tp1,
            tp2=draft.tp2,
            position_delta_eighths=draft.position_delta_eighths,
            position_after_eighths=draft.position_after_eighths or 0,
            pnl_pct=draft.current_pnl_pct,
            current_stock=_plan_decimal(draft.parse_payload, "plan_current_stock"),
            starter=_plan_decimal(draft.parse_payload, "plan_starter"),
            add_zone_low=_plan_decimal(draft.parse_payload, "plan_add_zone_low"),
            add_zone_high=_plan_decimal(draft.parse_payload, "plan_add_zone_high"),
            stock_sl=_plan_decimal(draft.parse_payload, "plan_stock_sl"),
            stock_pt1=_plan_decimal(draft.parse_payload, "plan_stock_pt1"),
            stock_pt2=_plan_decimal(draft.parse_payload, "plan_stock_pt2"),
            stock_pt3=_plan_decimal(draft.parse_payload, "plan_stock_pt3"),
            fib_0618=_plan_decimal(draft.parse_payload, "plan_fib_0618"),
            public_thesis=_public_thesis(draft.parse_payload),
            is_lotto=trade.is_lotto,
        )

    @staticmethod
    def _event_price(draft: TradeDraft):
        if draft.action_price is not None:
            return draft.action_price
        if draft.intent != "NEW_TRADE":
            return None
        if draft.entry_low is not None and draft.entry_high is not None:
            return (draft.entry_low + draft.entry_high) / 2
        return draft.entry_low if draft.entry_low is not None else draft.entry_high

    @staticmethod
    def _average_cost_after(
        trade: Trade,
        draft: TradeDraft,
        *,
        before_position: int,
        after_position: int,
    ) -> Decimal | None:
        if after_position <= 0:
            return None
        if draft.avg_cost is not None:
            return draft.avg_cost
        event_price = TradePublicationService._event_price(draft)
        if before_position == 0:
            return event_price or trade.avg_cost
        if (
            draft.action == TradeAction.ADD.value
            and after_position > before_position
            and trade.avg_cost is not None
            and event_price is not None
        ):
            added = after_position - before_position
            return (trade.avg_cost * before_position + event_price * added) / after_position
        return trade.avg_cost

    @staticmethod
    def _apply_trade_update(
        trade: Trade,
        draft: TradeDraft,
        after_position: int,
        *,
        avg_cost_after: Decimal | None = None,
    ) -> None:
        now = utc_now()
        trade.last_public_action = (
            f"ADD_{draft.action_stage}"
            if draft.action == TradeAction.ADD.value and draft.action_stage
            else draft.action
        )
        trade.position_eighths = after_position
        trade.max_position_eighths = max(trade.max_position_eighths, after_position)
        if draft.entry_low is not None:
            trade.entry_low = draft.entry_low
        if draft.entry_high is not None:
            trade.entry_high = draft.entry_high
        if avg_cost_after is not None:
            trade.avg_cost = avg_cost_after
        if draft.sl is not None:
            trade.sl = draft.sl
        if draft.tp1 is not None:
            trade.tp1 = draft.tp1
        if draft.tp2 is not None:
            trade.tp2 = draft.tp2
        if draft.action == TradeAction.ROLL.value:
            trade.ticker = draft.ticker or trade.ticker
            trade.expiry = draft.expiry or trade.expiry
            trade.strike = draft.strike or trade.strike
            trade.option_side = draft.option_side or trade.option_side
            trade.moomoo_option_code = None
        if trade.opened_at is None:
            trade.opened_at = now
        if trade.category == TradeCategory.SHORT_TERM.value:
            trade.option_contract_code = draft.option_contract_code
            trade.state = TradeState.ACTIVE.value
            trade.closed_at = None
            trade.position_eighths = 0
            trade.max_position_eighths = 0
            trade.version += 1
            return
        if (
            trade.category == TradeCategory.SWING.value
            and trade.tracking_mode == SIMPLE_TRACKED_SWING
        ):
            trade.option_contract_code = draft.option_contract_code or trade.option_contract_code
            if draft.action == TradeAction.CLOSE.value:
                trade.state = TradeState.CLOSED.value
                trade.closed_at = now
            else:
                trade.state = TradeState.ACTIVE.value
                trade.closed_at = None
            trade.position_eighths = 0
            trade.max_position_eighths = 0
            trade.version += 1
            return
        if draft.action == TradeAction.CANCEL.value:
            trade.state = TradeState.CANCELLED.value
            trade.closed_at = now
        elif after_position == 0:
            trade.state = TradeState.CLOSED.value
            trade.closed_at = now
        elif draft.action == TradeAction.RUNNER.value:
            trade.state = TradeState.RUNNER.value
            trade.closed_at = None
        else:
            trade.state = TradeState.ACTIVE.value
            trade.closed_at = None
        trade.version += 1

    @staticmethod
    def _existing_claim(publication: TradePublication, draft: TradeDraft) -> PublicationClaim:
        return PublicationClaim(
            publication_id=publication.id,
            draft_id=draft.id,
            claim_token=None,
            should_publish=False,
            already_published=(publication.status == PublicationStatus.PUBLISHED.value),
            channel_id=publication.channel_id,
            public_ref=publication.public_ref or "",
            card=None,
            message_id=publication.message_id,
        )

    @staticmethod
    async def _published_result(
        session: AsyncSession, publication: TradePublication
    ) -> PublicationResult:
        trade = await session.get(Trade, publication.trade_id)
        event = await session.get(TradeEvent, publication.trade_event_id)
        if (
            trade is None
            or event is None
            or publication.message_id is None
            or publication.draft_id is None
        ):
            raise PublicationValidationError("PUBLISHED_DATA_MISSING")
        return PublicationResult(
            publication_id=publication.id,
            draft_id=publication.draft_id,
            trade_id=trade.id,
            trade_event_id=event.id,
            message_id=publication.message_id,
            public_trade_id=trade.public_trade_id,
        )

    @staticmethod
    async def _audit(
        session: AsyncSession,
        *,
        draft: TradeDraft,
        actor_user_id: int | None,
        interaction_id: int | None,
        action_type: str,
        after: dict[str, object],
    ) -> None:
        effective_actor = actor_user_id or draft.reviewed_by
        if effective_actor is None:
            raise PublicationValidationError("APPROVER_REQUIRED")
        session.add(
            AuditLog(
                guild_id=draft.guild_id,
                actor_user_id=effective_actor,
                action_type=action_type,
                entity_type="trade_draft",
                entity_id=str(draft.id),
                before_json=None,
                after_json=after,
                discord_interaction_id=interaction_id,
            )
        )
