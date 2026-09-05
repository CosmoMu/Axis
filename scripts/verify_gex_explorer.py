#!/usr/bin/env python3
"""Live, read-only Massive cross-check for AXIS GEX Explorer Phase 1."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings  # noqa: E402
from app.integrations.gex_intraday_data import (  # noqa: E402
    MassiveGexIntradayProvider,
    MoomooGexIntradayProvider,
)
from app.integrations.gex_intraday_shadow import GexIntradayShadowBox  # noqa: E402
from app.integrations.gex_market_data import MassiveGexMarketDataProvider  # noqa: E402
from app.market_intelligence.gex_explorer.engine import build_gex_snapshot  # noqa: E402
from app.market_intelligence.gex_explorer.heatmap import render_gex_heatmap  # noqa: E402
from app.services.gex_explorer import GexPolicy  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tickers", nargs="*", default=["SPY", "QQQ", "NVDA", "TSLA", "AAPL", "SPX"])
    parser.add_argument("--skip-invalid", action="store_true")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Optional local directory for rendered visual-review PNG files.",
    )
    return parser.parse_args()


async def verify(tickers: list[str], *, invalid: bool, output_dir: Path | None = None) -> int:
    settings = Settings.load(PROJECT_ROOT)
    policy = GexPolicy.load(settings.gex_explorer_policy_path)
    provider = MassiveGexMarketDataProvider(
        api_key=settings.massive_api_key,
        base_url=settings.massive_base_url,
        concurrency=policy.provider_concurrency,
    )
    intraday_provider = MassiveGexIntradayProvider(
        api_key=settings.massive_api_key,
        base_url=settings.massive_base_url,
        interval_minutes=policy.intraday_interval_minutes,
    )
    shadow_box = GexIntradayShadowBox(
        MoomooGexIntradayProvider(
            host=settings.moomoo_host,
            port=settings.moomoo_port,
            interval_minutes=policy.intraday_interval_minutes,
        )
    )
    failures = 0
    for ticker in tickers:
        try:
            raw = await provider.fetch(ticker, policy)
            intraday = await intraday_provider.fetch(
                ticker,
                bar_count=policy.intraday_bar_count,
            )
            shadow = await shadow_box.compare(
                ticker=ticker,
                bar_count=policy.intraday_bar_count,
                primary=intraday,
                compared_at=datetime.now(UTC),
            )
            snapshot = build_gex_snapshot(
                ticker,
                raw.spot,
                raw.contracts,
                raw.fetched_at,
                risk_free_rate=policy.risk_free_rate,
                dividend_yield=policy.dividend_yield,
                regime_thresholds=policy.regime_thresholds,
                zone_relative_threshold=policy.zone_relative_threshold,
                score_weights=policy.score_weights,
                robust_percentile=policy.robust_percentile,
                node_neighbor_ratio=policy.node_neighbor_ratio,
                node_minimum_score=policy.node_minimum_score,
                major_minimum_score=policy.major_minimum_score,
                minor_minimum_score=policy.minor_minimum_score,
                magnet_minimum_score=policy.magnet_minimum_score,
                magnet_maximum_steps_from_spot=(policy.magnet_maximum_steps_from_spot),
                major_levels_per_side=policy.major_levels_per_side,
                minor_levels_per_side=policy.minor_levels_per_side,
                exposure_basis=policy.exposure_basis,
            )
            heatmap = render_gex_heatmap(snapshot, intraday.bars, policy)
            if output_dir is not None:
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / f"axis-gex-{ticker.lower()}.png").write_bytes(heatmap)
            by_strike_net = sum(point.net_gex for point in snapshot.by_strike)
            wall_check = max(
                (point for point in snapshot.by_strike if point.call_gex > 0),
                key=lambda point: point.call_gex,
            ).strike
            put_check = min(
                (point for point in snapshot.by_strike if point.put_gex < 0),
                key=lambda point: point.put_gex,
            ).strike
            point_map = {point.strike: point for point in snapshot.by_strike}
            classified_levels = (
                *snapshot.major_resistance,
                *snapshot.minor_resistance,
                *snapshot.major_support,
                *snapshot.minor_support,
            )
            positive_zone_strikes = {
                point.strike
                for point in snapshot.by_strike
                if any(zone.lower <= point.strike <= zone.upper for zone in snapshot.positive_zones)
            }
            negative_zone_strikes = {
                point.strike
                for point in snapshot.by_strike
                if any(zone.lower <= point.strike <= zone.upper for zone in snapshot.negative_zones)
            }
            checks = {
                "ten_expirations": len(snapshot.expirations) == policy.expiration_count,
                "net_reconciles": abs(by_strike_net - snapshot.net_gex) < 0.01,
                "call_wall_reconciles": wall_check == snapshot.call_wall,
                "put_wall_reconciles": put_check == snapshot.put_wall,
                "classified_levels_are_positive_net": all(
                    point_map[level].net_gex > 0 for level in classified_levels
                ),
                "positive_zones_are_positive_net": all(
                    point_map[strike].net_gex > 0 for strike in positive_zone_strikes
                ),
                "negative_zones_are_negative_net": all(
                    point_map[strike].net_gex < 0 for strike in negative_zone_strikes
                ),
                "magnet_is_single_positive_net": (
                    snapshot.gamma_magnet is None or point_map[snapshot.gamma_magnet].net_gex > 0
                ),
                "classified_levels_do_not_overlap_acceleration": (
                    not set(classified_levels) & negative_zone_strikes
                ),
                "listed_strikes_are_real": set(snapshot.listed_strikes)
                == {contract.strike for contract in raw.contracts},
                "png_valid": heatmap.startswith(b"\x89PNG"),
                "minute_bars_present": len(intraday.bars) >= policy.intraday_minimum_bars,
            }
            ok = all(checks.values())
            failures += int(not ok)
            print(
                json.dumps(
                    {
                        "ticker": ticker,
                        "ok": ok,
                        "spot": raw.spot,
                        "candidate_expirations": len(raw.candidate_expirations),
                        "used_expirations": len(raw.used_expirations),
                        "failed_expirations": len(raw.failed_expirations),
                        "contracts": len(raw.contracts),
                        "exposure_basis": snapshot.exposure_basis,
                        "market_status": raw.market_status,
                        "minute_provider": intraday.provider,
                        "minute_interval": policy.intraday_interval_minutes,
                        "minute_bars": len(intraday.bars),
                        "minute_source_timestamp": intraday.source_timestamp.isoformat(),
                        "moomoo_shadow": {
                            "candidate_provider": shadow.candidate_provider,
                            "candidate_bars": shadow.candidate_bar_count,
                            "overlap_bars": shadow.overlapping_bar_count,
                            "close_difference_pct": shadow.close_relative_difference_pct,
                            "timestamp_difference_seconds": (
                                shadow.source_timestamp_difference_seconds
                            ),
                            "error_code": shadow.candidate_error_code,
                        },
                        "source_timestamp": raw.source_timestamp.isoformat(),
                        "regime": snapshot.gamma_regime,
                        "levels": {
                            "gamma_magnet": snapshot.gamma_magnet,
                            "major_resistance": snapshot.major_resistance,
                            "minor_resistance": snapshot.minor_resistance,
                            "major_support": snapshot.major_support,
                            "minor_support": snapshot.minor_support,
                            "gamma_nodes": snapshot.gamma_nodes,
                            "zero_gamma": snapshot.zero_gamma,
                            "gross_call_wall_reference": snapshot.call_wall,
                            "gross_put_wall_reference": snapshot.put_wall,
                        },
                        "checks": checks,
                    },
                    ensure_ascii=False,
                )
            )
        except Exception as exc:
            failures += 1
            print(json.dumps({"ticker": ticker, "ok": False, "error": str(exc)}))
    if invalid:
        try:
            await provider.fetch("NOTAREALTICKER", policy)
        except Exception as exc:
            code = getattr(exc, "code", type(exc).__name__)
            ok = code in {"GEX_TICKER_NOT_FOUND", "GEX_NO_EXPIRATIONS"}
            failures += int(not ok)
            print(json.dumps({"ticker": "NOTAREALTICKER", "invalid_check": ok, "error": code}))
        else:
            failures += 1
            print(json.dumps({"ticker": "NOTAREALTICKER", "invalid_check": False}))
    return failures


def main() -> int:
    args = parse_args()
    return min(
        1,
        asyncio.run(
            verify(
                args.tickers,
                invalid=not args.skip_invalid,
                output_dir=args.output_dir,
            )
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
