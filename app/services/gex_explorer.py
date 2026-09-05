"""Application service for read-only, cached AXIS GEX queries."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from app.db.models import AuditLog
from app.db.session import Database
from app.integrations.gex_intraday_data import (
    GexIntradayDataProvider,
    GexIntradayResult,
)
from app.integrations.gex_intraday_shadow import (
    GexIntradayShadowBox,
    GexIntradayShadowComparison,
)
from app.integrations.gex_market_data import GexMarketDataProvider
from app.market_intelligence.gex_explorer.engine import build_gex_snapshot
from app.market_intelligence.gex_explorer.heatmap import render_gex_heatmap
from app.market_intelligence.gex_explorer.models import GexSnapshot

TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")
logger = logging.getLogger(__name__)


class GexExplorerError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def normalize_gex_ticker(raw: str) -> str:
    ticker = raw.strip().upper().removeprefix("$").removeprefix("US.")
    if not TICKER_PATTERN.fullmatch(ticker):
        raise GexExplorerError("GEX_TICKER_INVALID")
    return "SPX" if ticker in {"SPX", "SPXW"} else ticker


@dataclass(frozen=True, slots=True)
class GexPolicy:
    version: str
    expiration_count: int
    expiration_candidates: int
    expiration_horizon_days: int
    minimum_valid_expirations: int
    minimum_contracts_per_expiry: int
    strike_range_pct: float
    snapshot_page_limit: int
    snapshot_max_pages: int
    cache_seconds: int
    user_cooldown_seconds: int
    guild_fresh_requests_per_minute: int
    max_data_age_seconds: int
    max_latency_seconds: int
    provider_concurrency: int
    risk_free_rate: float
    dividend_yield: float
    regime_thresholds: tuple[float, float, float, float]
    exposure_basis: str
    zone_relative_threshold: float
    minor_level_relative_threshold: float
    heatmap_expiration_columns: int
    heatmap_strike_rows: int
    intraday_bar_count: int
    intraday_minimum_bars: int
    intraday_interval_minutes: int

    @classmethod
    def load(cls, path: Path) -> GexPolicy:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise GexExplorerError("GEX_POLICY_INVALID")
        regimes = payload.get("regime_thresholds")
        heatmap = payload.get("heatmap")
        intraday = payload.get("intraday")
        if (
            not isinstance(regimes, dict)
            or not isinstance(heatmap, dict)
            or not isinstance(intraday, dict)
        ):
            raise GexExplorerError("GEX_POLICY_INVALID")
        policy = cls(
            version=str(payload["version"]),
            expiration_count=int(payload["expiration_count"]),
            expiration_candidates=int(payload["expiration_candidates"]),
            expiration_horizon_days=int(payload["expiration_horizon_days"]),
            minimum_valid_expirations=int(payload["minimum_valid_expirations"]),
            minimum_contracts_per_expiry=int(payload["minimum_contracts_per_expiry"]),
            strike_range_pct=float(payload["strike_range_pct"]),
            snapshot_page_limit=int(payload["snapshot_page_limit"]),
            snapshot_max_pages=int(payload["snapshot_max_pages"]),
            cache_seconds=int(payload["cache_seconds"]),
            user_cooldown_seconds=int(payload["user_cooldown_seconds"]),
            guild_fresh_requests_per_minute=int(payload["guild_fresh_requests_per_minute"]),
            max_data_age_seconds=int(payload["max_data_age_seconds"]),
            max_latency_seconds=int(payload["max_latency_seconds"]),
            provider_concurrency=int(payload["provider_concurrency"]),
            risk_free_rate=float(payload["risk_free_rate"]),
            dividend_yield=float(payload["dividend_yield"]),
            regime_thresholds=(
                float(regimes["strong_positive"]),
                float(regimes["positive"]),
                float(regimes["negative"]),
                float(regimes["strong_negative"]),
            ),
            exposure_basis=str(payload["exposure_basis"]).strip().lower(),
            zone_relative_threshold=float(payload["zone_relative_threshold"]),
            minor_level_relative_threshold=float(payload["minor_level_relative_threshold"]),
            heatmap_expiration_columns=int(heatmap["expiration_columns"]),
            heatmap_strike_rows=int(heatmap["strike_rows"]),
            intraday_bar_count=int(intraday["bar_count"]),
            intraday_minimum_bars=int(intraday["minimum_bars"]),
            intraday_interval_minutes=int(intraday["interval_minutes"]),
        )
        policy.validate()
        return policy

    def validate(self) -> None:
        if not self.version.strip():
            raise GexExplorerError("GEX_POLICY_INVALID")
        positive = (
            self.expiration_count,
            self.expiration_candidates,
            self.minimum_valid_expirations,
            self.minimum_contracts_per_expiry,
            self.snapshot_page_limit,
            self.snapshot_max_pages,
            self.cache_seconds,
            self.user_cooldown_seconds,
            self.guild_fresh_requests_per_minute,
            self.max_data_age_seconds,
            self.max_latency_seconds,
            self.provider_concurrency,
            self.heatmap_expiration_columns,
            self.heatmap_strike_rows,
            self.intraday_bar_count,
            self.intraday_minimum_bars,
        )
        if any(value <= 0 for value in positive):
            raise GexExplorerError("GEX_POLICY_INVALID")
        if not (
            self.minimum_valid_expirations <= self.expiration_count <= self.expiration_candidates
        ):
            raise GexExplorerError("GEX_POLICY_INVALID")
        strong_positive, positive_threshold, negative_threshold, strong_negative = (
            self.regime_thresholds
        )
        if not strong_positive > positive_threshold > negative_threshold > strong_negative:
            raise GexExplorerError("GEX_POLICY_INVALID")
        if self.exposure_basis not in {"open_interest", "volume"}:
            raise GexExplorerError("GEX_POLICY_INVALID")
        if (
            not 0 < self.strike_range_pct < 1
            or not 0 < self.zone_relative_threshold <= 1
            or not 0 < self.minor_level_relative_threshold <= 1
        ):
            raise GexExplorerError("GEX_POLICY_INVALID")
        if self.intraday_minimum_bars > self.intraday_bar_count or self.intraday_bar_count > 1000:
            raise GexExplorerError("GEX_POLICY_INVALID")
        if self.intraday_interval_minutes not in {1, 5}:
            raise GexExplorerError("GEX_POLICY_INVALID")


@dataclass(frozen=True, slots=True)
class GexQueryResult:
    snapshot: GexSnapshot
    heatmap_png: bytes
    provider: str
    policy_version: str
    source_timestamp: datetime
    completed_at: datetime
    market_status: str
    stale: bool
    cache_hit: bool
    latency_ms: int
    candidate_expirations: int
    used_expirations: int
    failed_expirations: tuple[tuple[str, str], ...]
    intraday_provider: str
    intraday_source_timestamp: datetime
    intraday_session_date: date
    intraday_bar_count: int
    intraday_interval_minutes: int


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    created_monotonic: float
    result: GexQueryResult


class GexExplorerService:
    def __init__(
        self,
        database: Database,
        provider: GexMarketDataProvider,
        intraday_provider: GexIntradayDataProvider,
        policy: GexPolicy,
        *,
        shadow_intraday_provider: GexIntradayDataProvider | None = None,
    ) -> None:
        self.database = database
        self.provider = provider
        self.intraday_provider = intraday_provider
        self.policy = policy
        self.shadow_intraday = (
            GexIntradayShadowBox(shadow_intraday_provider)
            if shadow_intraday_provider is not None
            else None
        )
        self.shadow_observations: dict[str, GexIntradayShadowComparison] = {}
        self._shadow_tasks: set[asyncio.Task[None]] = set()
        self._cache: dict[tuple[str, str, str], _CacheEntry] = {}
        self._inflight: dict[tuple[str, str, str], asyncio.Task[GexQueryResult]] = {}
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
    ) -> GexQueryResult:
        symbol = normalize_gex_ticker(ticker)
        started_at = datetime.now(UTC)
        started = time.monotonic()
        await self._audit(
            "GEX_REQUESTED",
            guild_id=guild_id,
            actor_user_id=actor_user_id,
            ticker=symbol,
            interaction_id=interaction_id,
            requested_at=started_at,
        )
        key = (
            symbol,
            self.policy.version,
            f"{self.provider.name}+{self.intraday_provider.name}",
        )
        task: asyncio.Task[GexQueryResult] | None = None
        leader = False
        now = time.monotonic()
        async with self._lock:
            if enforce_rate_limits:
                user_key = (guild_id, actor_user_id)
                previous = self._last_user_request.get(user_key)
                if previous is not None and now - previous < self.policy.user_cooldown_seconds:
                    await self._audit_locked_rate_limit(
                        guild_id, actor_user_id, symbol, interaction_id, started_at, "USER_COOLDOWN"
                    )
                    raise GexExplorerError("GEX_USER_COOLDOWN")
                self._last_user_request[user_key] = now
            cached = self._cache.get(key)
            if cached is not None and now - cached.created_monotonic <= self.policy.cache_seconds:
                result = replace(
                    cached.result,
                    cache_hit=True,
                    latency_ms=max(0, int((time.monotonic() - started) * 1000)),
                    completed_at=datetime.now(UTC),
                )
            else:
                result = None
                task = self._inflight.get(key)
                if task is None:
                    if enforce_rate_limits:
                        fresh = self._guild_fresh_requests[guild_id]
                        while fresh and now - fresh[0] >= 60:
                            fresh.popleft()
                        if len(fresh) >= self.policy.guild_fresh_requests_per_minute:
                            await self._audit_locked_rate_limit(
                                guild_id,
                                actor_user_id,
                                symbol,
                                interaction_id,
                                started_at,
                                "GUILD_GLOBAL_LIMIT",
                            )
                            raise GexExplorerError("GEX_GUILD_RATE_LIMIT")
                        fresh.append(now)
                    task = asyncio.create_task(self._generate(symbol))
                    self._inflight[key] = task
                    leader = True
        if result is not None:
            await self._audit_result(
                "GEX_CACHE_HIT",
                result,
                guild_id,
                actor_user_id,
                symbol,
                interaction_id,
                started_at,
                True,
            )
            return result
        await self._audit(
            "GEX_CACHE_MISS",
            guild_id=guild_id,
            actor_user_id=actor_user_id,
            ticker=symbol,
            interaction_id=interaction_id,
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
                "GEX_GENERATED",
                result,
                guild_id,
                actor_user_id,
                symbol,
                interaction_id,
                started_at,
                True,
            )
            return result
        except Exception as exc:
            code = getattr(exc, "code", type(exc).__name__)
            await self._audit(
                "GEX_FAILED",
                guild_id=guild_id,
                actor_user_id=actor_user_id,
                ticker=symbol,
                interaction_id=interaction_id,
                requested_at=started_at,
                completed_at=datetime.now(UTC),
                latency_ms=max(0, int((time.monotonic() - started) * 1000)),
                success=False,
                error_type=str(code),
            )
            if isinstance(exc, GexExplorerError):
                raise
            provider_code = getattr(exc, "code", None)
            raise GexExplorerError(str(provider_code or "GEX_GENERATION_FAILED")) from exc
        finally:
            if leader:
                async with self._lock:
                    if self._inflight.get(key) is task:
                        self._inflight.pop(key, None)

    async def _generate(self, ticker: str) -> GexQueryResult:
        started = time.monotonic()
        provider_result, intraday_result = await asyncio.gather(
            self.provider.fetch(ticker, self.policy),
            self.intraday_provider.fetch(
                ticker,
                bar_count=self.policy.intraday_bar_count,
            ),
        )
        if len(provider_result.used_expirations) < self.policy.minimum_valid_expirations:
            raise GexExplorerError("GEX_EXPIRY_COVERAGE_INSUFFICIENT")
        if len(intraday_result.bars) < self.policy.intraday_minimum_bars:
            raise GexExplorerError("GEX_INTRADAY_COVERAGE_INSUFFICIENT")
        completed = datetime.now(UTC)
        try:
            snapshot = build_gex_snapshot(
                ticker,
                provider_result.spot,
                provider_result.contracts,
                completed,
                risk_free_rate=self.policy.risk_free_rate,
                dividend_yield=self.policy.dividend_yield,
                regime_thresholds=self.policy.regime_thresholds,
                zone_relative_threshold=self.policy.zone_relative_threshold,
                minor_level_relative_threshold=self.policy.minor_level_relative_threshold,
                exposure_basis=self.policy.exposure_basis,
            )
        except (TypeError, ValueError) as exc:
            raise GexExplorerError("GEX_DATA_QUALITY_FAILED") from exc
        if len(snapshot.expirations) < self.policy.minimum_valid_expirations:
            raise GexExplorerError("GEX_EXPIRY_COVERAGE_INSUFFICIENT")
        warnings = list(snapshot.data_warnings)
        if len(provider_result.used_expirations) < self.policy.expiration_count:
            warnings.append(
                "有效到期日覆盖不足目标值："
                f"{len(provider_result.used_expirations)}/{self.policy.expiration_count}"
            )
            snapshot = replace(snapshot, data_warnings=tuple(warnings))
        try:
            heatmap = render_gex_heatmap(snapshot, intraday_result.bars, self.policy)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise GexExplorerError("GEX_RENDER_FAILED") from exc
        gex_age = max(
            0.0,
            (provider_result.fetched_at - provider_result.source_timestamp).total_seconds(),
        )
        intraday_age = max(
            0.0,
            (provider_result.fetched_at - intraday_result.source_timestamp).total_seconds(),
        )
        result = GexQueryResult(
            snapshot=snapshot,
            heatmap_png=heatmap,
            provider=provider_result.provider,
            policy_version=self.policy.version,
            source_timestamp=provider_result.source_timestamp,
            completed_at=completed,
            market_status=provider_result.market_status,
            stale=max(gex_age, intraday_age) > self.policy.max_data_age_seconds,
            cache_hit=False,
            latency_ms=max(0, int((time.monotonic() - started) * 1000)),
            candidate_expirations=len(provider_result.candidate_expirations),
            used_expirations=len(snapshot.expirations),
            failed_expirations=tuple(
                (expiration.isoformat(), code)
                for expiration, code in provider_result.failed_expirations
            ),
            intraday_provider=intraday_result.provider,
            intraday_source_timestamp=intraday_result.source_timestamp,
            intraday_session_date=intraday_result.session_date,
            intraday_bar_count=len(intraday_result.bars),
            intraday_interval_minutes=self.policy.intraday_interval_minutes,
        )
        self._schedule_intraday_shadow(ticker, intraday_result)
        return result

    def _schedule_intraday_shadow(
        self,
        ticker: str,
        primary: GexIntradayResult,
    ) -> None:
        if self.shadow_intraday is None:
            return
        task = asyncio.create_task(self._run_intraday_shadow(ticker, primary))
        self._shadow_tasks.add(task)
        task.add_done_callback(self._shadow_tasks.discard)

    async def _run_intraday_shadow(self, ticker: str, primary: GexIntradayResult) -> None:
        assert self.shadow_intraday is not None
        comparison = await self.shadow_intraday.compare(
            ticker=ticker,
            bar_count=self.policy.intraday_bar_count,
            primary=primary,
            compared_at=datetime.now(UTC),
        )
        self.shadow_observations[ticker] = comparison
        if comparison.candidate_error_code is not None:
            logger.warning(
                "event=gex_intraday_shadow candidate=%s ticker=%s status=unavailable error_type=%s",
                comparison.candidate_provider,
                ticker,
                comparison.candidate_error_code,
            )
            return
        logger.info(
            "event=gex_intraday_shadow primary=%s candidate=%s ticker=%s status=compared "
            "primary_bars=%d candidate_bars=%d overlap=%d close_diff_pct=%.6f "
            "timestamp_diff_seconds=%.3f",
            comparison.primary_provider,
            comparison.candidate_provider,
            ticker,
            comparison.primary_bar_count,
            comparison.candidate_bar_count,
            comparison.overlapping_bar_count,
            comparison.close_relative_difference_pct or 0.0,
            comparison.source_timestamp_difference_seconds or 0.0,
        )

    async def _audit_locked_rate_limit(
        self,
        guild_id: int,
        actor_user_id: int,
        ticker: str,
        interaction_id: int | None,
        requested_at: datetime,
        reason: str,
    ) -> None:
        await self._audit(
            "GEX_RATE_LIMITED",
            guild_id=guild_id,
            actor_user_id=actor_user_id,
            ticker=ticker,
            interaction_id=interaction_id,
            requested_at=requested_at,
            completed_at=datetime.now(UTC),
            success=False,
            error_type=reason,
        )

    async def _audit_result(
        self,
        event: str,
        result: GexQueryResult,
        guild_id: int,
        actor_user_id: int,
        ticker: str,
        interaction_id: int | None,
        requested_at: datetime,
        success: bool,
    ) -> None:
        await self._audit(
            event,
            guild_id=guild_id,
            actor_user_id=actor_user_id,
            ticker=ticker,
            interaction_id=interaction_id,
            requested_at=requested_at,
            completed_at=result.completed_at,
            latency_ms=result.latency_ms,
            cache_hit=result.cache_hit,
            provider=result.provider,
            success=success,
            used_expirations=result.used_expirations,
        )

    async def _audit(
        self,
        event: str,
        *,
        guild_id: int,
        actor_user_id: int,
        ticker: str,
        interaction_id: int | None,
        requested_at: datetime,
        completed_at: datetime | None = None,
        latency_ms: int | None = None,
        cache_hit: bool | None = None,
        provider: str | None = None,
        success: bool | None = None,
        error_type: str | None = None,
        used_expirations: int | None = None,
    ) -> None:
        after: dict[str, Any] = {
            "requested_at": requested_at.isoformat(),
            "completed_at": completed_at.isoformat() if completed_at else None,
            "latency_ms": latency_ms,
            "cache_hit": cache_hit,
            "provider": provider or self.provider.name,
            "policy_version": self.policy.version,
            "success": success,
            "error_type": error_type,
            "used_expirations": used_expirations,
        }
        async with self.database.session() as session:
            session.add(
                AuditLog(
                    guild_id=guild_id,
                    actor_user_id=actor_user_id,
                    action_type=event,
                    entity_type="gex_request",
                    entity_id=ticker,
                    before_json=None,
                    after_json=after,
                    discord_interaction_id=interaction_id,
                )
            )
            await session.commit()
