#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict
from datetime import date, datetime
from enum import Enum
from pathlib import Path

MARKER = "AXIS_COSMOS_JSON:"


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return str(value.value)
    raise TypeError(type(value).__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Local AXIS to Cosmos stock analyst bridge")
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--no-chart", action="store_true")
    args = parser.parse_args()
    runtime_root = args.runtime_root.resolve()
    ticker = args.ticker.strip().upper()
    if not re.fullmatch(r"[A-Z0-9.\-]{1,12}", ticker):
        print(MARKER + json.dumps({"ok": False, "error": "INVALID_TICKER"}))
        return 2
    if str(runtime_root) not in sys.path:
        sys.path.insert(0, str(runtime_root))

    try:
        from apps.cosmos_market.stock_analysis_service import StockAnalysisService
        from packages.cosmos_core.config import Settings

        settings = Settings.from_env(runtime_root / ".env")
        service = StockAnalysisService(
            settings,
            card_root=runtime_root / "data/cards/axis-stock-analysis",
        )
        if args.no_chart:
            analysis = service.analyze(ticker)
            card = None
        else:
            analysis, card = service.query(ticker)
        payload = {
            "ok": True,
            "analysis": asdict(analysis),
            "card_path": str(card.resolve()) if card is not None else None,
        }
        print(MARKER + json.dumps(payload, ensure_ascii=False, default=_json_default))
        return 0
    except Exception as exc:
        print(
            MARKER
            + json.dumps(
                {"ok": False, "error": type(exc).__name__}, ensure_ascii=False
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
