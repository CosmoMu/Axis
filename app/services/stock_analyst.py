"""Read-only, audited application service for on-demand AXIS Stock Analyst queries."""

from __future__ import annotations

import asyncio
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from app.db.models import AuditLog
from app.db.session import Database
from app.market_intelligence.stock_analyst.engine import STRATEGY_VERSION
from app.market_intelligence.stock_analyst.models import StockAnalysis
from app.market_intelligence.stock_analyst.service import (
    AxisStockAnalystError,
    AxisStockAnalystService,
)

TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.-]{0,11}$")


class StockAnalystError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def normalize_stock_ticker(raw: str) -> str:
    ticker = raw.strip().upper().removeprefix("$").removeprefix("US.")
    if not TICKER_PATTERN.fullmatch(ticker):
        raise StockAnalystError("AXIS_STOCK_SYMBOL_INVALID")
    return ticker


@dataclass(frozen=True, slots=True)
class StockAnalystPolicy:
    version: str
    provider: str
    daily_lookback_calendar_days: int
    minimum_daily_sessions: int
    maximum_data_age_seconds: int
    timeout_seconds: int
    provider_concurrency: int
    timeframe: str
    chart_sessions: int
    cache_seconds: int
    user_cooldown_seconds: int
    guild_fresh_requests_per_minute: int
    maximum_latency_seconds: int

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        version_override: str | None = None,
    ) -> StockAnalystPolicy:
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            market = payload["market_data"]
            analysis = payload["analysis"]
            runtime = payload["runtime"]
            policy = cls(
                version=version_override or str(payload["version"]),
                provider=str(market["provider"]).lower(),
                daily_lookback_calendar_days=int(market["daily_lookback_calendar_days"]),
                minimum_daily_sessions=int(market["minimum_daily_sessions"]),
                maximum_data_age_seconds=int(market["maximum_data_age_seconds"]),
                timeout_seconds=int(market["timeout_seconds"]),
                provider_concurrency=int(market["provider_concurrency"]),
                timeframe=str(analysis["timeframe"]).upper(),
                chart_sessions=int(analysis["chart_sessions"]),
                cache_seconds=int(runtime["cache_seconds"]),
                user_cooldown_seconds=int(runtime["user_cooldown_seconds"]),
                guild_fresh_requests_per_minute=int(runtime["guild_fresh_requests_per_minute"]),
                maximum_latency_seconds=int(runtime["maximum_latency_seconds"]),
            )
        except (KeyError, OSError, TypeError, ValueError, yaml.YAMLError) as exc:
            raise StockAnalystError("STOCK_ANALYST_POLICY_INVALID") from exc
        policy.validate()
        return policy

    def validate(self) -> None:
        positive = (
            self.daily_lookback_calendar_days,
            self.minimum_daily_sessions,
            self.maximum_data_age_seconds,
            self.timeout_seconds,
            self.provider_concurrency,
            self.chart_sessions,
            self.cache_seconds,
            self.user_cooldown_seconds,
            self.guild_fresh_requests_per_minute,
            self.maximum_latency_seconds,
        )
        if (
            any(value <= 0 for value in positive)
            or self.provider != "massive"
            or self.timeframe != "1D"
            or self.version != STRATEGY_VERSION
            or self.minimum_daily_sessions < 120
            or self.chart_sessions != 82
        ):
            raise StockAnalystError("STOCK_ANALYST_POLICY_INVALID")

    @property
    def cache_signature(self) -> str:
        return (
            f"{self.timeframe}:{self.daily_lookback_calendar_days}:"
            f"{self.minimum_daily_sessions}:{self.chart_sessions}"
        )


@dataclass(frozen=True, slots=True)
class StockAnalystQueryResult:
    analysis: StockAnalysis
    chart_png: bytes
    structured_result: dict[str, Any]
    provider: str
    strategy_version: str
    source_timestamp: datetime
    completed_at: datetime
    market_status: str
    stale: bool
    cache_hit: bool
    latency_ms: int


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    created_monotonic: float
    result: StockAnalystQueryResult


class StockAnalystQueryService:
    def __init__(
        self,
        database: Database,
        analyst: AxisStockAnalystService,
        policy: StockAnalystPolicy,
    ) -> None:
        self.database = database
        self.analyst = analyst
        self.policy = policy
        self._cache: dict[tuple[str, str, str, str], _CacheEntry] = {}
        self._inflight: dict[tuple[str, str, str, str], asyncio.Task[StockAnalystQueryResult]] = {}
        self._last_user_request: dict[tuple[int, int], float] = {}
        self._guild_fresh_requests: defaultdict[int, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def query(
        self,
        *,
        guild_id: int,
        actor_user_id: int,
        ticker: str,
        interaction_id: int | None = None,
        enforce_rate_limits: bool = True,
    ) -> StockAnalystQueryResult:
        symbol = normalize_stock_ticker(ticker)
        started_at = datetime.now(UTC)
        started = time.monotonic()
        await self._audit(
            "STOCK_ANALYST_REQUESTED",
            guild_id,
            actor_user_id,
            symbol,
            interaction_id,
            requested_at=started_at,
        )
        provider = getattr(self.analyst.provider, "name", "unknown")
        key = (symbol, self.policy.version, provider, self.policy.cache_signature)
        task: asyncio.Task[StockAnalystQueryResult] | None = None
        leader = False
        cached_result: StockAnalystQueryResult | None = None
        now = time.monotonic()
        async with self._lock:
            if enforce_rate_limits:
                user_key = (guild_id, actor_user_id)
                previous = self._last_user_request.get(user_key)
                if previous is not None and now - previous < self.policy.user_cooldown_seconds:
                    await self._audit_rate_limit(
                        guild_id, actor_user_id, symbol, interaction_id, started_at, "USER_COOLDOWN"
                    )
                    raise StockAnalystError("STOCK_ANALYST_USER_COOLDOWN")
                self._last_user_request[user_key] = now
            cached = self._cache.get(key)
            if cached is not None and now - cached.created_monotonic <= self.policy.cache_seconds:
                completed = datetime.now(UTC)
                cached_result = replace(
                    cached.result,
                    completed_at=completed,
                    stale=self._is_stale(
                        cached.result.source_timestamp,
                        cached.result.market_status,
                        completed,
                    ),
                    cache_hit=True,
                    latency_ms=max(0, int((time.monotonic() - started) * 1000)),
                )
            else:
                task = self._inflight.get(key)
                if task is None:
                    if enforce_rate_limits:
                        requests = self._guild_fresh_requests[guild_id]
                        while requests and now - requests[0] >= 60:
                            requests.popleft()
                        if len(requests) >= self.policy.guild_fresh_requests_per_minute:
                            await self._audit_rate_limit(
                                guild_id,
                                actor_user_id,
                                symbol,
                                interaction_id,
                                started_at,
                                "GUILD_GLOBAL_LIMIT",
                            )
                            raise StockAnalystError("STOCK_ANALYST_GUILD_RATE_LIMIT")
                        requests.append(now)
                    task = asyncio.create_task(self._generate(symbol))
                    self._inflight[key] = task
                    leader = True
        if cached_result is not None:
            await self._audit_result(
                "STOCK_ANALYST_CACHE_HIT",
                cached_result,
                guild_id,
                actor_user_id,
                symbol,
                interaction_id,
                started_at,
            )
            return cached_result
        await self._audit(
            "STOCK_ANALYST_CACHE_MISS",
            guild_id,
            actor_user_id,
            symbol,
            interaction_id,
            requested_at=started_at,
        )
        assert task is not None
        try:
            generated = await task
            result = replace(
                generated,
                cache_hit=False,
                latency_ms=max(0, int((time.monotonic() - started) * 1000)),
                completed_at=datetime.now(UTC),
            )
            if leader:
                async with self._lock:
                    self._cache[key] = _CacheEntry(time.monotonic(), generated)
            await self._audit_result(
                "STOCK_ANALYST_GENERATED",
                result,
                guild_id,
                actor_user_id,
                symbol,
                interaction_id,
                started_at,
            )
            return result
        except Exception as exc:
            code = (
                str(exc)
                if isinstance(exc, AxisStockAnalystError)
                else getattr(exc, "code", type(exc).__name__)
            )
            await self._audit(
                "STOCK_ANALYST_FAILED",
                guild_id,
                actor_user_id,
                symbol,
                interaction_id,
                requested_at=started_at,
                completed_at=datetime.now(UTC),
                latency_ms=max(0, int((time.monotonic() - started) * 1000)),
                success=False,
                error_type=str(code),
            )
            if isinstance(exc, StockAnalystError):
                raise
            if isinstance(exc, AxisStockAnalystError):
                raise StockAnalystError(str(exc)) from exc
            raise StockAnalystError("STOCK_ANALYST_COMMAND_FAILURE") from exc
        finally:
            if leader:
                async with self._lock:
                    if self._inflight.get(key) is task:
                        self._inflight.pop(key, None)

    async def _generate(self, ticker: str) -> StockAnalystQueryResult:
        started = time.monotonic()
        core = await self.analyst.query(ticker, include_chart=True)
        if core.analysis is None or core.chart_png is None:
            raise StockAnalystError("STOCK_ANALYST_DATA_QUALITY_FAILURE")
        completed = datetime.now(UTC)
        source_timestamp = _timestamp(core.context.get("market_timestamp"))
        provider = str(core.context.get("provider") or "unknown")
        market_status = str(core.context.get("market_status") or "unknown").lower()
        structured = self._structured_result(
            core.analysis,
            provider,
            source_timestamp,
            market_status,
            completed,
        )
        return StockAnalystQueryResult(
            analysis=core.analysis,
            chart_png=core.chart_png,
            structured_result=structured,
            provider=provider,
            strategy_version=self.policy.version,
            source_timestamp=source_timestamp,
            completed_at=completed,
            market_status=market_status,
            stale=self._is_stale(source_timestamp, market_status, completed),
            cache_hit=False,
            latency_ms=max(0, int((time.monotonic() - started) * 1000)),
        )

    def _structured_result(
        self,
        analysis: StockAnalysis,
        provider: str,
        source_timestamp: datetime,
        market_status: str,
        generated_at: datetime,
    ) -> dict[str, Any]:
        primary = max(analysis.scenarios, key=lambda item: item.model_weight_percent)
        bullish = max(
            (item for item in analysis.scenarios if item.direction == "CALL"),
            key=lambda item: item.model_weight_percent,
        )
        bearish = max(
            (item for item in analysis.scenarios if item.direction == "PUT"),
            key=lambda item: item.model_weight_percent,
        )
        bias = (
            "BULLISH"
            if analysis.trend_score >= 68
            else "NEUTRAL_TO_BULLISH"
            if analysis.trend_score >= 55
            else "BEARISH"
            if analysis.trend_score <= 32
            else "NEUTRAL_TO_BEARISH"
            if analysis.trend_score <= 45
            else "NEUTRAL"
        )
        return {
            "ticker": analysis.ticker,
            "price": analysis.current_price,
            "market_timestamp": source_timestamp.isoformat(),
            "provider": provider,
            "freshness": (
                "STALE"
                if self._is_stale(source_timestamp, market_status, generated_at)
                else "LATEST_AVAILABLE"
                if market_status != "open"
                else "CURRENT"
            ),
            "timeframes": ("1D",),
            "market_structure": analysis.trend_label,
            "trend": analysis.trend_label,
            "bias": bias,
            "bias_score": analysis.trend_score,
            "support_levels": tuple(item.price for item in analysis.support_levels),
            "resistance_levels": tuple(item.price for item in analysis.resistance_levels),
            "poc": analysis.point_of_control,
            "vah": analysis.value_area_high,
            "val": analysis.value_area_low,
            "volume_state": analysis.money_flow.label,
            "rvol": None,
            "indicator_summary": dict(analysis.indicator_scores),
            "bullish_trigger": bullish.trigger_zh,
            "bearish_trigger": bearish.trigger_zh,
            "invalidation": primary.invalidation,
            "targets": primary.targets,
            "scenarios": tuple(
                {
                    "id": item.scenario_id,
                    "label": item.label_zh,
                    "direction": item.direction,
                    "weight": item.model_weight_percent,
                    "trigger": item.trigger_zh,
                    "targets": item.targets,
                    "invalidation": item.invalidation,
                }
                for item in analysis.scenarios
            ),
            "top_scenario": primary.label_zh,
            "scenario_weight": primary.model_weight_percent,
            "strategy_version": self.policy.version,
            "generated_at": generated_at.isoformat(),
        }

    def _is_stale(
        self,
        source_timestamp: datetime,
        market_status: str,
        now: datetime,
    ) -> bool:
        return (
            market_status == "open"
            and max(0.0, (now - source_timestamp).total_seconds())
            > self.policy.maximum_data_age_seconds
        )

    async def _audit_rate_limit(
        self,
        guild_id: int,
        actor_user_id: int,
        ticker: str,
        interaction_id: int | None,
        requested_at: datetime,
        reason: str,
    ) -> None:
        await self._audit(
            "STOCK_ANALYST_RATE_LIMITED",
            guild_id,
            actor_user_id,
            ticker,
            interaction_id,
            requested_at=requested_at,
            completed_at=datetime.now(UTC),
            success=False,
            error_type=reason,
        )

    async def _audit_result(
        self,
        event: str,
        result: StockAnalystQueryResult,
        guild_id: int,
        actor_user_id: int,
        ticker: str,
        interaction_id: int | None,
        requested_at: datetime,
    ) -> None:
        await self._audit(
            event,
            guild_id,
            actor_user_id,
            ticker,
            interaction_id,
            requested_at=requested_at,
            completed_at=result.completed_at,
            latency_ms=result.latency_ms,
            cache_hit=result.cache_hit,
            success=True,
        )

    async def _audit(
        self,
        event: str,
        guild_id: int,
        actor_user_id: int,
        ticker: str,
        interaction_id: int | None,
        *,
        requested_at: datetime,
        completed_at: datetime | None = None,
        latency_ms: int | None = None,
        cache_hit: bool | None = None,
        success: bool | None = None,
        error_type: str | None = None,
    ) -> None:
        async with self.database.session() as session:
            session.add(
                AuditLog(
                    guild_id=guild_id,
                    actor_user_id=actor_user_id,
                    action_type=event,
                    entity_type="stock_analyst_request",
                    entity_id=ticker,
                    before_json=None,
                    after_json={
                        "requested_at": requested_at.isoformat(),
                        "completed_at": completed_at.isoformat() if completed_at else None,
                        "latency_ms": latency_ms,
                        "provider": getattr(self.analyst.provider, "name", "unknown"),
                        "cache_hit": cache_hit,
                        "strategy_version": self.policy.version,
                        "success": success,
                        "error_type": error_type,
                    },
                    discord_interaction_id=interaction_id,
                )
            )
            await session.commit()


def _timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise StockAnalystError("STOCK_ANALYST_DATA_QUALITY_FAILURE") from exc
    else:
        raise StockAnalystError("STOCK_ANALYST_DATA_QUALITY_FAILURE")
    if parsed.tzinfo is None:
        raise StockAnalystError("STOCK_ANALYST_DATA_QUALITY_FAILURE")
    return parsed.astimezone(UTC)
