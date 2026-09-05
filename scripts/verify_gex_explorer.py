#!/usr/bin/env python3
"""Live, read-only Massive cross-check for AXIS GEX Explorer Phase 1."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings  # noqa: E402
from app.integrations.gex_market_data import MassiveGexMarketDataProvider  # noqa: E402
from app.market_intelligence.gex_explorer.engine import build_gex_snapshot  # noqa: E402
from app.market_intelligence.gex_explorer.heatmap import render_gex_heatmap  # noqa: E402
from app.services.gex_explorer import GexPolicy  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tickers", nargs="*", default=["SPY", "QQQ", "NVDA", "TSLA", "AAPL", "SPX"])
    parser.add_argument("--skip-invalid", action="store_true")
    return parser.parse_args()


async def verify(tickers: list[str], *, invalid: bool) -> int:
    settings = Settings.load(PROJECT_ROOT)
    policy = GexPolicy.load(settings.gex_explorer_policy_path)
    provider = MassiveGexMarketDataProvider(
        api_key=settings.massive_api_key,
        base_url=settings.massive_base_url,
        concurrency=policy.provider_concurrency,
    )
    failures = 0
    for ticker in tickers:
        try:
            raw = await provider.fetch(ticker, policy)
            snapshot = build_gex_snapshot(
                ticker,
                raw.spot,
                raw.contracts,
                raw.fetched_at,
                risk_free_rate=policy.risk_free_rate,
                dividend_yield=policy.dividend_yield,
                regime_thresholds=policy.regime_thresholds,
                zone_relative_threshold=policy.zone_relative_threshold,
            )
            heatmap = render_gex_heatmap(snapshot, policy)
            by_strike_net = sum(point.net_gex for point in snapshot.by_strike)
            wall_check = max(
                (point for point in snapshot.by_strike if point.call_gex > 0),
                key=lambda point: point.call_gex,
            ).strike
            put_check = min(
                (point for point in snapshot.by_strike if point.put_gex < 0),
                key=lambda point: point.put_gex,
            ).strike
            checks = {
                "ten_expirations": len(raw.used_expirations) == policy.expiration_count,
                "net_reconciles": abs(by_strike_net - snapshot.net_gex) < 0.01,
                "call_wall_reconciles": wall_check == snapshot.call_wall,
                "put_wall_reconciles": put_check == snapshot.put_wall,
                "png_valid": heatmap.startswith(b"\x89PNG"),
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
                        "market_status": raw.market_status,
                        "source_timestamp": raw.source_timestamp.isoformat(),
                        "regime": snapshot.gamma_regime,
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
    return min(1, asyncio.run(verify(args.tickers, invalid=not args.skip_invalid)))


if __name__ == "__main__":
    raise SystemExit(main())
