"""Adapters over the existing AXIS Stock Analyst and GEX services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.market_intelligence.research_engine.models import ResearchComponent
from app.services.gex_explorer import GexExplorerService
from app.services.stock_analyst import StockAnalystQueryService


@dataclass(frozen=True, slots=True)
class CollectedComponent:
    component: ResearchComponent
    chart_png: bytes | None = None


def _future_source(source_timestamp: datetime, as_of: datetime) -> bool:
    return source_timestamp.astimezone(UTC) > as_of.astimezone(UTC) + timedelta(seconds=2)


class AxisTechnicalResearchProvider:
    name = "axis-stock-analyst"

    def __init__(self, service: StockAnalystQueryService) -> None:
        self.service = service

    @property
    def version(self) -> str:
        return self.service.policy.version

    async def fetch(
        self, *, guild_id: int, actor_user_id: int, ticker: str, as_of: datetime
    ) -> CollectedComponent:
        result = await self.service.query(
            guild_id=guild_id,
            actor_user_id=actor_user_id,
            ticker=ticker,
            enforce_rate_limits=False,
            bypass_cooldowns=True,
        )
        if _future_source(result.source_timestamp, as_of):
            raise RuntimeError("RESEARCH_TECHNICAL_LOOKAHEAD_BLOCKED")
        data = dict(result.structured_result)
        data["component_version"] = result.strategy_version
        return CollectedComponent(
            ResearchComponent(
                component="technical",
                status="AVAILABLE",
                provider=result.provider,
                as_of=as_of,
                source_timestamp=result.source_timestamp,
                retrieval_timestamp=result.completed_at,
                freshness="STALE" if result.stale else data.get("freshness", "CURRENT"),
                coverage=1.0,
                data=data,
                warnings=("STALE_DATA",) if result.stale else (),
            ),
            result.chart_png,
        )


class AxisGexResearchProvider:
    name = "axis-gex-explorer"

    def __init__(self, service: GexExplorerService) -> None:
        self.service = service

    @property
    def version(self) -> str:
        return self.service.policy.version

    async def fetch(
        self, *, guild_id: int, actor_user_id: int, ticker: str, as_of: datetime
    ) -> CollectedComponent:
        result = await self.service.query(
            guild_id=guild_id,
            actor_user_id=actor_user_id,
            ticker=ticker,
            enforce_rate_limits=False,
            bypass_cooldowns=True,
        )
        if _future_source(result.source_timestamp, as_of):
            raise RuntimeError("RESEARCH_GEX_LOOKAHEAD_BLOCKED")
        snapshot = result.snapshot
        data: dict[str, Any] = {
            "spot": snapshot.spot,
            "net_gex": snapshot.net_gex,
            "gamma_regime": snapshot.gamma_regime,
            "current_bias": snapshot.current_bias,
            "gamma_flip": snapshot.zero_gamma,
            "gamma_magnet": snapshot.gamma_magnet,
            "call_wall": snapshot.call_wall,
            "put_wall": snapshot.put_wall,
            "major_support": list(snapshot.major_support),
            "minor_support": list(snapshot.minor_support),
            "major_resistance": list(snapshot.major_resistance),
            "minor_resistance": list(snapshot.minor_resistance),
            "negative_acceleration_zones": [
                {"lower": item.lower, "upper": item.upper, "peak": item.peak}
                for item in snapshot.negative_zones
            ],
            "near_term_expiration": (
                snapshot.near_term_expiration.isoformat()
                if snapshot.near_term_expiration is not None
                else None
            ),
            "near_term_net_gex": snapshot.near_term_net_gex,
            "near_term_regime": snapshot.near_term_regime,
            "bullish_trigger": snapshot.bullish_trigger,
            "bearish_trigger": snapshot.bearish_trigger,
            "component_version": result.policy_version,
        }
        warnings = tuple(snapshot.data_warnings) + (("STALE_DATA",) if result.stale else ())
        return CollectedComponent(
            ResearchComponent(
                component="gex",
                status="AVAILABLE",
                provider=result.provider,
                as_of=as_of,
                source_timestamp=result.source_timestamp,
                retrieval_timestamp=result.completed_at,
                freshness="STALE" if result.stale else "CURRENT",
                coverage=min(1.0, result.used_expirations / max(1, result.candidate_expirations)),
                data=data,
                warnings=warnings,
            ),
            result.heatmap_png,
        )
