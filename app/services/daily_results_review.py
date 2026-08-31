from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    AuditLog,
    DailyResultsItem,
    DailyResultsReview,
    GuildConfig,
    ShortTermTracking,
    Trade,
    TradeEvent,
    utc_now,
)
from app.db.session import Database
from app.domain.enums import TradeCategory, TradeState
from app.services.daily_summary import _trade_result_details, _weighted_return
from app.services.trading_calendar import TradingCalendarService

DEFAULT_SECTION_ORDER = ("SHORT_TERM", "SWING", "LEAPS")
ACTIVE_SHORT_TERM_STATES = ("ACTIVE", "OVERNIGHT_ACTIVE")
SECTION_LABELS = {
    "SHORT_TERM": "SHORT-TERM",
    "SWING": "SWING",
    "LEAPS": "LEAPS",
}
EXCLUSION_REASONS = (
    "DUPLICATE_SIGNAL",
    "DATA_QUALITY_ISSUE",
    "BAD_QUOTE",
    "WRONG_CONTRACT",
    "MANUAL_CORRECTION",
    "NOT_FOR_PUBLIC_SUMMARY",
    "OTHER",
)


class ResultsReviewError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ResultsItemView:
    id: uuid.UUID
    trade_id: uuid.UUID
    public_trade_id: str
    category: str
    contract: str
    included: bool
    display_result_pct: Decimal | None
    display_text: str
    exclusion_reason: str | None


@dataclass(frozen=True, slots=True)
class ResultsReviewView:
    id: uuid.UUID
    trading_date: date
    status: str
    scheduled_publish_at: datetime
    review_channel_id: int
    public_channel_id: int
    review_message_id: int | None
    public_message_id: int | None
    snapshot: dict[str, object]
    items: tuple[ResultsItemView, ...]
    locked: bool


@dataclass(frozen=True, slots=True)
class ResultsPublishClaim:
    review_id: uuid.UUID
    channel_id: int
    public_ref: str
    snapshot: dict[str, object]
    message_id: int | None
    should_publish: bool


def _bounds(trading_date: date, timezone_name: str) -> tuple[datetime, datetime]:
    zone = ZoneInfo(timezone_name)
    start = datetime.combine(trading_date, time.min, zone)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def _number(value: object) -> str:
    parsed = Decimal(str(value))
    return f"{parsed:f}".rstrip("0").rstrip(".") if "." in f"{parsed:f}" else f"{parsed:f}"


def _percent(value: Decimal | None) -> str:
    if value is None:
        return "N/A"
    rendered = f"{value:+.2f}".rstrip("0").rstrip(".")
    return f"{rendered}%"


def _contract(payload: dict[str, object]) -> str:
    side = "C" if payload["option_side"] == "CALL" else "P"
    lotto = " (LOTTO)" if payload.get("is_lotto") else ""
    return f"{payload['ticker']} {_number(payload['strike'])}{side}{lotto}"


def _display_line(item: DailyResultsItem) -> str:
    if item.display_text_override:
        return item.display_text_override.strip()
    payload = item.snapshot_json
    head = f"{payload['public_trade_id']} · {_contract(payload)}"
    if item.category == TradeCategory.SHORT_TERM.value:
        side = "C" if payload["option_side"] == "CALL" else "P"
        return (
            f"{payload['ticker']} {_number(payload['strike'])}{side} "
            f"{_percent(item.display_result_pct)}"
        )
    corrected = item.original_result_pct is not None
    details = []
    if corrected:
        details.append(f"修正结果 {_percent(item.display_result_pct)}")
    else:
        details.extend(
            f"{str(label)} {_percent(Decimal(str(value)))}"
            for label, value in payload.get("tp_returns", [])
        )
        if not details and payload.get("exit_label"):
            exit_value = (
                Decimal(str(payload["exit_return_pct"]))
                if payload.get("exit_return_pct") is not None
                else item.display_result_pct
            )
            details.append(
                f"{payload['exit_label']} {_percent(exit_value)}"
            )
    highest = payload.get("highest_return_pct")
    if highest is not None:
        details.append(f"最高收益 {_percent(Decimal(str(highest)))}")
    if not details:
        details.append(f"最终收益 {_percent(item.display_result_pct)}")
    return f"{head}\n" + " · ".join(details)


class DailyResultsReviewService:
    def __init__(
        self,
        database: Database,
        *,
        timezone_name: str = "America/New_York",
        final_publish_time: str = "16:15",
        calendar: TradingCalendarService | None = None,
    ) -> None:
        self.database = database
        self.timezone_name = timezone_name
        self.final_publish_time = final_publish_time
        self.calendar = calendar or TradingCalendarService()

    def draft_ready_date(self, now: datetime, delay_minutes: int) -> date | None:
        current = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
        local_date = current.astimezone(ZoneInfo(self.timezone_name)).date()
        if not self.calendar.is_trading_day(local_date):
            return None
        ready_at = self.calendar.session_close(local_date) + timedelta(minutes=delay_minutes)
        return local_date if current >= ready_at else None

    def scheduled_publish_at(self, trading_date: date) -> datetime:
        hour, minute = (int(part) for part in self.final_publish_time.split(":"))
        return datetime.combine(
            trading_date,
            time(hour, minute),
            ZoneInfo(self.timezone_name),
        ).astimezone(UTC)

    async def prepare_review(self, guild_id: int, trading_date: date) -> ResultsReviewView:
        if not self.calendar.is_trading_day(trading_date):
            raise ResultsReviewError("NOT_A_TRADING_DAY")
        async with self.database.session() as session:
            existing = await session.scalar(
                select(DailyResultsReview).where(
                    DailyResultsReview.guild_id == guild_id,
                    DailyResultsReview.trading_date == trading_date,
                )
            )
            if existing is not None:
                review_id = existing.id
            else:
                config = await session.get(GuildConfig, guild_id)
                if config is None:
                    raise ResultsReviewError("GUILD_CONFIG_NOT_FOUND")
                if config.results_review_channel_id is None:
                    raise ResultsReviewError("RESULTS_REVIEW_CHANNEL_NOT_CONFIGURED")
                if config.results_channel_id is None:
                    raise ResultsReviewError("RESULTS_CHANNEL_NOT_CONFIGURED")
                start, end = _bounds(trading_date, self.timezone_name)
                tracking_rows = (
                    await session.execute(
                        select(ShortTermTracking, Trade)
                        .join(Trade, Trade.id == ShortTermTracking.trade_id)
                        .where(
                            ShortTermTracking.guild_id == guild_id,
                            (
                                ShortTermTracking.tracking_state.in_(
                                    ACTIVE_SHORT_TERM_STATES
                                )
                                | (
                                    (ShortTermTracking.tracking_state == "STOPPED")
                                    & (ShortTermTracking.tracking_ended_at >= start)
                                    & (ShortTermTracking.tracking_ended_at < end)
                                )
                            ),
                        )
                        .order_by(Trade.public_trade_id)
                    )
                ).all()
                closed = list(
                    await session.scalars(
                        select(Trade)
                        .where(
                            Trade.guild_id == guild_id,
                            Trade.category.in_(
                                (TradeCategory.SWING.value, TradeCategory.LEAPS.value)
                            ),
                            Trade.state == TradeState.CLOSED.value,
                            Trade.closed_at >= start,
                            Trade.closed_at < end,
                        )
                        .order_by(Trade.category, Trade.public_trade_id)
                    )
                )
                closed_ids = [trade.id for trade in closed]
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
                events_by_trade: dict[uuid.UUID, list[TradeEvent]] = {}
                for event in events:
                    events_by_trade.setdefault(event.trade_id, []).append(event)

                review = DailyResultsReview(
                    guild_id=guild_id,
                    trading_date=trading_date,
                    status="DRAFT",
                    draft_snapshot={},
                    display_overrides={},
                    scheduled_publish_at=self.scheduled_publish_at(trading_date),
                )
                session.add(review)
                await session.flush()
                order = 0
                for tracking, trade in tracking_rows:
                    session.add(
                        DailyResultsItem(
                            review_id=review.id,
                            trade_id=trade.id,
                            category=TradeCategory.SHORT_TERM.value,
                            display_result_pct=tracking.highest_return_pct,
                            included=True,
                            display_order=order,
                            snapshot_json=self._trade_payload(trade),
                        )
                    )
                    order += 1
                for trade in closed:
                    trade_events = events_by_trade.get(trade.id, [])
                    final_return = trade.final_return_pct
                    if final_return is None:
                        final_return = _weighted_return(trade_events)
                    tp_returns, highest, exit_label, exit_return = _trade_result_details(
                        trade_events, final_return
                    )
                    payload = self._trade_payload(trade)
                    payload.update(
                        {
                            "tp_returns": [
                                [label, str(return_pct)] for label, return_pct in tp_returns
                            ],
                            "highest_return_pct": (str(highest) if highest is not None else None),
                            "exit_label": exit_label,
                            "exit_return_pct": (
                                str(exit_return) if exit_return is not None else None
                            ),
                        }
                    )
                    session.add(
                        DailyResultsItem(
                            review_id=review.id,
                            trade_id=trade.id,
                            category=trade.category,
                            display_result_pct=final_return,
                            included=True,
                            display_order=order,
                            snapshot_json=payload,
                        )
                    )
                    order += 1
                await session.flush()
                items = list(
                    await session.scalars(
                        select(DailyResultsItem)
                        .where(DailyResultsItem.review_id == review.id)
                        .order_by(DailyResultsItem.display_order, DailyResultsItem.id)
                    )
                )
                review.draft_snapshot = self._snapshot(review, items, public=False)
                self._audit(
                    session,
                    review,
                    actor_user_id=0,
                    action_type="DAILY_RESULTS_DRAFT_CREATED",
                    after={"eligible_trade_count": len(items)},
                )
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
                    existing = await session.scalar(
                        select(DailyResultsReview).where(
                            DailyResultsReview.guild_id == guild_id,
                            DailyResultsReview.trading_date == trading_date,
                        )
                    )
                    if existing is None:
                        raise
                    review_id = existing.id
                else:
                    review_id = review.id
        return await self.get_review(review_id)

    async def get_review(self, review_id: uuid.UUID) -> ResultsReviewView:
        async with self.database.session() as session:
            review = await session.get(DailyResultsReview, review_id)
            if review is None:
                raise ResultsReviewError("REVIEW_NOT_FOUND")
            config = await session.get(GuildConfig, review.guild_id)
            if (
                config is None
                or config.results_review_channel_id is None
                or config.results_channel_id is None
            ):
                raise ResultsReviewError("RESULTS_CHANNEL_NOT_CONFIGURED")
            items = list(
                await session.scalars(
                    select(DailyResultsItem)
                    .where(DailyResultsItem.review_id == review.id)
                    .order_by(DailyResultsItem.display_order, DailyResultsItem.id)
                )
            )
            snapshot = self._snapshot(review, items, public=False)
            return ResultsReviewView(
                id=review.id,
                trading_date=review.trading_date,
                status=review.status,
                scheduled_publish_at=review.scheduled_publish_at,
                review_channel_id=config.results_review_channel_id,
                public_channel_id=config.results_channel_id,
                review_message_id=review.discord_review_message_id,
                public_message_id=review.discord_public_message_id,
                snapshot=snapshot,
                items=tuple(self._item_view(item) for item in items),
                locked=review.final_snapshot is not None,
            )

    async def review_for_date(self, guild_id: int, trading_date: date) -> uuid.UUID | None:
        async with self.database.session() as session:
            return await session.scalar(
                select(DailyResultsReview.id).where(
                    DailyResultsReview.guild_id == guild_id,
                    DailyResultsReview.trading_date == trading_date,
                )
            )

    async def pending_review_ids(self, guild_id: int) -> tuple[uuid.UUID, ...]:
        async with self.database.session() as session:
            rows = await session.scalars(
                select(DailyResultsReview.id)
                .where(
                    DailyResultsReview.guild_id == guild_id,
                    DailyResultsReview.status.in_(("DRAFT", "REVIEWED")),
                )
                .order_by(DailyResultsReview.trading_date)
            )
            return tuple(rows)

    async def due_review_ids(self, guild_id: int, now: datetime) -> tuple[uuid.UUID, ...]:
        current = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
        async with self.database.session() as session:
            rows = await session.scalars(
                select(DailyResultsReview.id)
                .where(
                    DailyResultsReview.guild_id == guild_id,
                    DailyResultsReview.status.in_(("DRAFT", "REVIEWED")),
                    DailyResultsReview.scheduled_publish_at <= current,
                )
                .order_by(DailyResultsReview.trading_date)
            )
            return tuple(rows)

    async def attach_review_message(self, review_id: uuid.UUID, message_id: int) -> None:
        async with self.database.session() as session:
            review = await session.get(DailyResultsReview, review_id)
            if review is None:
                raise ResultsReviewError("REVIEW_NOT_FOUND")
            review.discord_review_message_id = message_id
            await session.commit()

    async def set_included(
        self,
        item_id: uuid.UUID,
        *,
        included: bool,
        actor_user_id: int,
        reason: str | None = None,
    ) -> uuid.UUID:
        if not included and reason not in EXCLUSION_REASONS:
            raise ResultsReviewError("EXCLUSION_REASON_REQUIRED")
        async with self.database.session() as session:
            item = await session.scalar(
                select(DailyResultsItem).where(DailyResultsItem.id == item_id).with_for_update()
            )
            if item is None:
                raise ResultsReviewError("RESULTS_ITEM_NOT_FOUND")
            review = await session.scalar(
                select(DailyResultsReview)
                .where(DailyResultsReview.id == item.review_id)
                .with_for_update()
            )
            self._assert_editable(review)
            before = {
                "included": item.included,
                "exclusion_reason": item.exclusion_reason,
            }
            item.included = included
            item.excluded_by = None if included else actor_user_id
            item.excluded_at = None if included else utc_now()
            item.exclusion_reason = None if included else reason
            review.status = "REVIEWED"
            await self._refresh_draft_snapshot(session, review)
            self._audit(
                session,
                review,
                actor_user_id=actor_user_id,
                action_type=("DAILY_RESULTS_REINCLUDED" if included else "DAILY_RESULTS_EXCLUDED"),
                trade_id=item.trade_id,
                before=before,
                after={"included": included, "exclusion_reason": item.exclusion_reason},
                reason=reason,
            )
            await session.commit()
            return review.id

    async def edit_item_display(
        self,
        item_id: uuid.UUID,
        *,
        display_text: str | None,
        actor_user_id: int,
    ) -> uuid.UUID:
        async with self.database.session() as session:
            item = await session.scalar(
                select(DailyResultsItem).where(DailyResultsItem.id == item_id).with_for_update()
            )
            if item is None:
                raise ResultsReviewError("RESULTS_ITEM_NOT_FOUND")
            review = await session.scalar(
                select(DailyResultsReview)
                .where(DailyResultsReview.id == item.review_id)
                .with_for_update()
            )
            self._assert_editable(review)
            before = item.display_text_override
            item.display_text_override = display_text.strip()[:1000] if display_text else None
            review.status = "REVIEWED"
            await self._refresh_draft_snapshot(session, review)
            self._audit(
                session,
                review,
                actor_user_id=actor_user_id,
                action_type="DAILY_RESULTS_DISPLAY_EDITED",
                trade_id=item.trade_id,
                before={"display_text_override": before},
                after={"display_text_override": item.display_text_override},
            )
            await session.commit()
            return review.id

    async def edit_card(
        self,
        review_id: uuid.UUID,
        *,
        title: str | None,
        section_order: str | None,
        footer: str | None,
        actor_user_id: int,
    ) -> None:
        async with self.database.session() as session:
            review = await session.scalar(
                select(DailyResultsReview)
                .where(DailyResultsReview.id == review_id)
                .with_for_update()
            )
            self._assert_editable(review)
            parsed_order = self._parse_section_order(section_order)
            before = dict(review.display_overrides)
            review.display_overrides = {
                "title": title.strip()[:200] if title else None,
                "section_order": list(parsed_order),
                "footer": footer.strip()[:1000] if footer else None,
            }
            review.status = "REVIEWED"
            await self._refresh_draft_snapshot(session, review)
            self._audit(
                session,
                review,
                actor_user_id=actor_user_id,
                action_type="DAILY_RESULTS_CARD_EDITED",
                before=before,
                after=review.display_overrides,
            )
            await session.commit()

    async def correct_result(
        self,
        item_id: uuid.UUID,
        *,
        corrected_value: Decimal,
        reason: str,
        actor_user_id: int,
    ) -> uuid.UUID:
        if not reason.strip():
            raise ResultsReviewError("CORRECTION_REASON_REQUIRED")
        async with self.database.session() as session:
            item = await session.scalar(
                select(DailyResultsItem).where(DailyResultsItem.id == item_id).with_for_update()
            )
            if item is None:
                raise ResultsReviewError("RESULTS_ITEM_NOT_FOUND")
            review = await session.scalar(
                select(DailyResultsReview)
                .where(DailyResultsReview.id == item.review_id)
                .with_for_update()
            )
            if review is None:
                raise ResultsReviewError("REVIEW_NOT_FOUND")
            before_value = item.display_result_pct
            if item.original_result_pct is None:
                item.original_result_pct = before_value
            item.display_result_pct = corrected_value
            item.correction_reason = reason.strip()[:1000]
            item.corrected_by = actor_user_id
            item.corrected_at = utc_now()
            published_correction = review.status in {"PUBLISHED", "CORRECTED"}
            review.status = "CORRECTED" if published_correction else "REVIEWED"
            await self._refresh_draft_snapshot(session, review)
            self._audit(
                session,
                review,
                actor_user_id=actor_user_id,
                action_type=(
                    "DAILY_RESULTS_PUBLIC_CORRECTION"
                    if published_correction
                    else "DAILY_RESULTS_RESULT_CORRECTED"
                ),
                trade_id=item.trade_id,
                before={"display_result_pct": str(before_value)},
                after={"display_result_pct": str(corrected_value)},
                reason=item.correction_reason,
            )
            await session.commit()
            return review.id

    async def claim_publish(
        self,
        review_id: uuid.UUID,
        *,
        actor_user_id: int,
        scheduled: bool,
    ) -> ResultsPublishClaim:
        async with self.database.session() as session:
            review = await session.scalar(
                select(DailyResultsReview)
                .where(DailyResultsReview.id == review_id)
                .with_for_update()
            )
            if review is None:
                raise ResultsReviewError("REVIEW_NOT_FOUND")
            config = await session.get(GuildConfig, review.guild_id)
            if config is None or config.results_channel_id is None:
                raise ResultsReviewError("RESULTS_CHANNEL_NOT_CONFIGURED")
            if review.discord_public_message_id is not None:
                return ResultsPublishClaim(
                    review_id=review.id,
                    channel_id=config.results_channel_id,
                    public_ref=self.public_ref(review.trading_date),
                    snapshot=review.final_snapshot or {},
                    message_id=review.discord_public_message_id,
                    should_publish=False,
                )
            if review.final_snapshot is None:
                items = list(
                    await session.scalars(
                        select(DailyResultsItem)
                        .where(DailyResultsItem.review_id == review.id)
                        .order_by(DailyResultsItem.display_order, DailyResultsItem.id)
                    )
                )
                review.final_snapshot = self._snapshot(review, items, public=True)
            review.status = "REVIEWED"
            self._audit(
                session,
                review,
                actor_user_id=actor_user_id,
                action_type=(
                    "DAILY_RESULTS_SCHEDULED_PUBLISH" if scheduled else "DAILY_RESULTS_PUBLISH_NOW"
                ),
                after={"public_ref": self.public_ref(review.trading_date)},
            )
            snapshot = dict(review.final_snapshot)
            await session.commit()
            return ResultsPublishClaim(
                review_id=review.id,
                channel_id=config.results_channel_id,
                public_ref=self.public_ref(review.trading_date),
                snapshot=snapshot,
                message_id=None,
                should_publish=True,
            )

    async def finalize_publish(
        self,
        review_id: uuid.UUID,
        *,
        message_id: int,
        actor_user_id: int,
    ) -> None:
        async with self.database.session() as session:
            review = await session.scalar(
                select(DailyResultsReview)
                .where(DailyResultsReview.id == review_id)
                .with_for_update()
            )
            if review is None:
                raise ResultsReviewError("REVIEW_NOT_FOUND")
            if review.discord_public_message_id is not None:
                return
            review.discord_public_message_id = message_id
            review.published_at = utc_now()
            review.status = "PUBLISHED"
            self._audit(
                session,
                review,
                actor_user_id=actor_user_id,
                action_type="DAILY_RESULTS_PUBLISHED",
                after={"discord_public_message_id": message_id},
            )
            await session.commit()

    async def current_public_snapshot(self, review_id: uuid.UUID) -> dict[str, object]:
        async with self.database.session() as session:
            review = await session.get(DailyResultsReview, review_id)
            if review is None:
                raise ResultsReviewError("REVIEW_NOT_FOUND")
            items = list(
                await session.scalars(
                    select(DailyResultsItem)
                    .where(DailyResultsItem.review_id == review.id)
                    .order_by(DailyResultsItem.display_order, DailyResultsItem.id)
                )
            )
            return self._snapshot(review, items, public=True)

    @staticmethod
    def public_ref(trading_date: date) -> str:
        return f"DAILY-RESULTS-{trading_date:%Y%m%d}"

    @staticmethod
    def _trade_payload(trade: Trade) -> dict[str, object]:
        return {
            "public_trade_id": trade.public_trade_id,
            "ticker": trade.ticker,
            "strike": str(trade.strike),
            "option_side": trade.option_side,
            "is_lotto": trade.is_lotto,
        }

    @staticmethod
    def _assert_editable(review: DailyResultsReview | None) -> None:
        if review is None:
            raise ResultsReviewError("REVIEW_NOT_FOUND")
        if review.final_snapshot is not None or review.status in {"PUBLISHED", "CORRECTED"}:
            raise ResultsReviewError("REVIEW_LOCKED")

    async def _refresh_draft_snapshot(self, session, review: DailyResultsReview) -> None:
        items = list(
            await session.scalars(
                select(DailyResultsItem)
                .where(DailyResultsItem.review_id == review.id)
                .order_by(DailyResultsItem.display_order, DailyResultsItem.id)
            )
        )
        review.draft_snapshot = self._snapshot(review, items, public=False)

    def _snapshot(
        self,
        review: DailyResultsReview,
        items: list[DailyResultsItem],
        *,
        public: bool,
    ) -> dict[str, object]:
        overrides = review.display_overrides or {}
        order = self._parse_section_order(overrides.get("section_order"))
        sections = []
        for category in order:
            lines = []
            for item in items:
                if item.category != category or (public and not item.included):
                    continue
                marker = "" if public else ("✓ " if item.included else "✕ ")
                lines.append(marker + _display_line(item))
            sections.append(
                {
                    "category": category,
                    "label": SECTION_LABELS[category],
                    "lines": lines,
                }
            )
        title = overrides.get("title") or "AXIS DAILY RESULTS"
        if not public:
            title = f"{title} · DRAFT"
        footer = overrides.get("footer") or (
            "Past performance does not guarantee future results." if public else "Manager Review"
        )
        output: dict[str, object] = {
            "title": title,
            "trading_date": review.trading_date.isoformat(),
            "sections": sections,
            "footer": footer,
        }
        if not public:
            output.update(
                {
                    "status": review.status,
                    "scheduled_publish_at": review.scheduled_publish_at.isoformat(),
                }
            )
        return output

    @staticmethod
    def _parse_section_order(value: object) -> tuple[str, ...]:
        if value is None or value == "":
            return DEFAULT_SECTION_ORDER
        if isinstance(value, str):
            parts = tuple(
                part.strip().upper().replace("-", "_")
                for part in re.split(r"[,>\n]+", value)
                if part.strip()
            )
        elif isinstance(value, (list, tuple)):
            parts = tuple(str(part).strip().upper().replace("-", "_") for part in value)
        else:
            raise ResultsReviewError("SECTION_ORDER_INVALID")
        if len(parts) != 3 or set(parts) != set(DEFAULT_SECTION_ORDER):
            raise ResultsReviewError("SECTION_ORDER_INVALID")
        return parts

    @staticmethod
    def _item_view(item: DailyResultsItem) -> ResultsItemView:
        payload = item.snapshot_json
        return ResultsItemView(
            id=item.id,
            trade_id=item.trade_id,
            public_trade_id=str(payload["public_trade_id"]),
            category=item.category,
            contract=_contract(payload),
            included=item.included,
            display_result_pct=item.display_result_pct,
            display_text=_display_line(item),
            exclusion_reason=item.exclusion_reason,
        )

    @staticmethod
    def _audit(
        session,
        review: DailyResultsReview,
        *,
        actor_user_id: int,
        action_type: str,
        trade_id: uuid.UUID | None = None,
        before: dict[str, object] | None = None,
        after: dict[str, object] | None = None,
        reason: str | None = None,
    ) -> None:
        after_json = dict(after or {})
        if reason:
            after_json["reason"] = reason
        session.add(
            AuditLog(
                guild_id=review.guild_id,
                actor_user_id=actor_user_id,
                action_type=action_type,
                entity_type="daily_results_review",
                entity_id=str(review.id),
                before_json=before,
                after_json={
                    **after_json,
                    "review_id": str(review.id),
                    "trade_id": str(trade_id) if trade_id else None,
                },
                discord_interaction_id=None,
            )
        )
