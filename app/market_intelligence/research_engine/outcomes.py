"""Underlying 1/3/5-session outcome resolution for completed research runs."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import select

from app.db.models import (
    AuditLog,
    ResearchOutcome,
    ResearchReflection,
    ResearchRun,
    utc_now,
)
from app.db.session import Database
from app.market_intelligence.stock_analyst.models import DailyBar, StockMarketBundle
from app.services.trading_calendar import TradingCalendarService

logger = logging.getLogger(__name__)


class OutcomeDailyBarProvider(Protocol):
    async def fetch(self, symbol: str) -> StockMarketBundle: ...


def _utc(value: datetime) -> datetime:
    return (value if value.tzinfo is not None else value.replace(tzinfo=UTC)).astimezone(UTC)


def _session_after(calendar: TradingCalendarService, base: date, count: int) -> date:
    first = base if calendar.is_trading_day(base) else calendar.next_trading_day(base)
    sessions = calendar.calendar.sessions_window(first, count + 1)
    return calendar._python_date(sessions[-1])


def _bars_through(
    bars: tuple[DailyBar, ...], *, after: datetime, through: date
) -> tuple[DailyBar, ...]:
    return tuple(
        bar
        for bar in sorted(bars, key=lambda item: item.timestamp)
        if _utc(bar.timestamp) > _utc(after) and bar.timestamp.date() <= through
    )


class ResearchOutcomeService:
    def __init__(
        self,
        database: Database,
        provider: OutcomeDailyBarProvider,
        calendar: TradingCalendarService,
        *,
        benchmark_ticker: str,
        horizons: tuple[int, ...],
    ) -> None:
        self.database = database
        self.provider = provider
        self.calendar = calendar
        self.benchmark_ticker = benchmark_ticker
        self.horizons = horizons

    async def seed(self, research_run_id: uuid.UUID, *, as_of: datetime) -> None:
        async with self.database.session() as session:
            existing = set(
                (
                    await session.execute(
                        select(ResearchOutcome.horizon_trading_days).where(
                            ResearchOutcome.research_run_id == research_run_id
                        )
                    )
                ).scalars()
            )
            for horizon in self.horizons:
                if horizon not in existing:
                    session.add(
                        ResearchOutcome(
                            research_run_id=research_run_id,
                            horizon_trading_days=horizon,
                            benchmark_ticker=self.benchmark_ticker,
                            target_session_date=_session_after(
                                self.calendar, as_of.date(), horizon
                            ),
                            status="PENDING",
                        )
                    )
            await session.commit()

    async def resolve_due(self, *, now: datetime | None = None) -> int:
        current = now or utc_now()
        async with self.database.session() as session:
            rows = (
                await session.execute(
                    select(ResearchOutcome, ResearchRun)
                    .join(ResearchRun, ResearchRun.id == ResearchOutcome.research_run_id)
                    .where(
                        ResearchOutcome.status == "PENDING",
                        ResearchOutcome.target_session_date <= current.date(),
                    )
                )
            ).all()
        resolved = 0
        for outcome, run in rows:
            try:
                if current < self.calendar.session_close(outcome.target_session_date):
                    continue
                await self._resolve(outcome.id, run, current)
                resolved += 1
            except Exception as exc:
                logger.warning(
                    "event=research_outcome_resolution_failed error_type=%s",
                    type(exc).__name__,
                    exc_info=True,
                )
                async with self.database.session() as session:
                    row = await session.get(ResearchOutcome, outcome.id)
                    if row is not None:
                        row.error_type = "RESEARCH_OUTCOME_RESOLUTION_FAILURE"
                        await session.commit()
        return resolved

    async def _resolve(
        self, outcome_id: uuid.UUID, run: ResearchRun, resolved_at: datetime
    ) -> None:
        ticker_bundle, benchmark_bundle = await self._fetch_pair(run.ticker)
        ticker_bars = _bars_through(
            ticker_bundle.bars, after=run.as_of, through=(await self._target_date(outcome_id))
        )
        benchmark_bars = _bars_through(
            benchmark_bundle.bars,
            after=run.as_of,
            through=await self._target_date(outcome_id),
        )
        view = run.final_view_json or {}
        start_price = view.get("price")
        if not isinstance(start_price, (int, float)) or not ticker_bars or not benchmark_bars:
            raise RuntimeError("RESEARCH_OUTCOME_DATA_UNAVAILABLE")
        benchmark_before = [
            bar for bar in benchmark_bundle.bars if _utc(bar.timestamp) <= _utc(run.as_of)
        ]
        if not benchmark_before:
            raise RuntimeError("RESEARCH_OUTCOME_BENCHMARK_UNAVAILABLE")
        raw_return = ticker_bars[-1].close / float(start_price) - 1
        benchmark_return = benchmark_bars[-1].close / benchmark_before[-1].close - 1
        mfe = max(bar.high / float(start_price) - 1 for bar in ticker_bars)
        mae = min(bar.low / float(start_price) - 1 for bar in ticker_bars)
        targets = [
            float(value) for value in view.get("targets", []) if isinstance(value, (int, float))
        ]
        invalidation = view.get("invalidation")
        stance = str(run.research_stance or "NEUTRAL")
        bullish = "BULLISH" in stance
        target_hit = (
            any(
                (
                    max(bar.high for bar in ticker_bars) >= target
                    if bullish
                    else min(bar.low for bar in ticker_bars) <= target
                )
                for target in targets
            )
            if targets and stance != "NEUTRAL"
            else None
        )
        invalidation_hit = (
            (
                min(bar.low for bar in ticker_bars) <= float(invalidation)
                if bullish
                else max(bar.high for bar in ticker_bars) >= float(invalidation)
            )
            if isinstance(invalidation, (int, float)) and stance != "NEUTRAL"
            else None
        )
        resolution_timestamp = max(ticker_bars[-1].timestamp, benchmark_bars[-1].timestamp)
        async with self.database.session() as session:
            outcome = await session.get(ResearchOutcome, outcome_id)
            if outcome is None:
                return
            outcome.status = "RESOLVED"
            outcome.raw_return = Decimal(str(raw_return))
            outcome.benchmark_return = Decimal(str(benchmark_return))
            outcome.alpha_return = Decimal(str(raw_return - benchmark_return))
            outcome.max_favorable_excursion = Decimal(str(mfe))
            outcome.max_adverse_excursion = Decimal(str(mae))
            outcome.primary_target_hit = target_hit
            outcome.invalidation_hit = invalidation_hit
            outcome.resolution_timestamp = resolution_timestamp
            outcome.resolved_at = resolved_at
            reflection = ResearchReflection(
                research_run_id=run.id,
                research_outcome_id=outcome.id,
                ticker=run.ticker,
                horizon_trading_days=outcome.horizon_trading_days,
                reflection_json=self._deterministic_reflection(
                    raw_return=raw_return,
                    alpha_return=raw_return - benchmark_return,
                    target_hit=target_hit,
                    invalidation_hit=invalidation_hit,
                ),
                provider="axis-deterministic",
                model=None,
                prompt_version="axis-outcome-reflection-v1",
                schema_version="axis-research-reflection-v1",
                resolution_timestamp=resolution_timestamp,
            )
            session.add(reflection)
            session.add(
                AuditLog(
                    guild_id=run.guild_id,
                    actor_user_id=run.created_by_discord_user_id,
                    action_type="RESEARCH_OUTCOME_RESOLVED",
                    entity_type="research_run",
                    entity_id=str(run.id),
                    before_json=None,
                    after_json={
                        "ticker": run.ticker,
                        "horizon": outcome.horizon_trading_days,
                        "resolution_timestamp": resolution_timestamp.isoformat(),
                    },
                    discord_interaction_id=None,
                )
            )
            session.add(
                AuditLog(
                    guild_id=run.guild_id,
                    actor_user_id=run.created_by_discord_user_id,
                    action_type="RESEARCH_REFLECTION_CREATED",
                    entity_type="research_run",
                    entity_id=str(run.id),
                    before_json=None,
                    after_json={"horizon": outcome.horizon_trading_days},
                    discord_interaction_id=None,
                )
            )
            await session.commit()

    async def _target_date(self, outcome_id: uuid.UUID) -> date:
        async with self.database.session() as session:
            outcome = await session.get(ResearchOutcome, outcome_id)
            if outcome is None:
                raise RuntimeError("RESEARCH_OUTCOME_NOT_FOUND")
            return outcome.target_session_date

    async def _fetch_pair(self, ticker: str) -> tuple[StockMarketBundle, StockMarketBundle]:
        if ticker == self.benchmark_ticker:
            bundle = await self.provider.fetch(ticker)
            return bundle, bundle
        import asyncio

        ticker_bundle, benchmark_bundle = await asyncio.gather(
            self.provider.fetch(ticker), self.provider.fetch(self.benchmark_ticker)
        )
        return ticker_bundle, benchmark_bundle

    @staticmethod
    def _deterministic_reflection(
        *,
        raw_return: float,
        alpha_return: float,
        target_hit: bool | None,
        invalidation_hit: bool | None,
    ) -> dict[str, Any]:
        return {
            "what_worked": ["Primary target was reached"] if target_hit else [],
            "what_failed": ["Primary target was not reached"] if target_hit is False else [],
            "missed_risk": ["Invalidation was reached"] if invalidation_hit else [],
            "data_gap": [],
            "lesson": (
                "The underlying outperformed its benchmark over the resolved horizon."
                if alpha_return > 0
                else "The underlying did not outperform its benchmark over the resolved horizon."
            ),
            "raw_return": raw_return,
            "alpha_return": alpha_return,
        }
