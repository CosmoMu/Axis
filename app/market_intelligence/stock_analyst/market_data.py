"""Moomoo OpenD market-data adapter for AXIS Stock Analyst."""

from __future__ import annotations

import asyncio
import threading
import time
from contextlib import suppress
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.market_intelligence.stock_analyst.engine import infer_sector_etf
from app.market_intelligence.stock_analyst.models import DailyBar, StockMarketBundle

ET = ZoneInfo("America/New_York")
_HISTORY_REQUEST_LOCK = threading.Lock()
_LAST_HISTORY_REQUEST_AT = 0.0
_MINIMUM_HISTORY_INTERVAL_SECONDS = 1.1
MINIMUM_ANALYSIS_SESSIONS = 50


class StockMarketDataError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def normalize_us_symbol(ticker: str) -> str:
    value = ticker.strip().upper().removeprefix("$")
    if not value or len(value) > 12 or any(not (char.isalnum() or char in ".-") for char in value):
        raise StockMarketDataError("AXIS_STOCK_SYMBOL_INVALID")
    return value.removeprefix("US.")


class MoomooDailyBarProvider:
    """Read-only daily bars through the AXIS-owned local OpenD connection."""

    def __init__(self, host: str, port: int, lookback_days: int = 620) -> None:
        self.host = host
        self.port = port
        self.lookback_days = lookback_days

    async def fetch(self, ticker: str) -> StockMarketBundle:
        return await asyncio.to_thread(self._fetch_sync, normalize_us_symbol(ticker))

    def _fetch_sync(self, ticker: str) -> StockMarketBundle:
        try:
            from moomoo import KL_FIELD, RET_OK, AuType, KLType, OpenQuoteContext, SysConfig
        except Exception as exc:
            raise StockMarketDataError("MOOMOO_SDK_UNAVAILABLE") from exc
        SysConfig.enable_console_log(False)
        context = None
        try:
            context = OpenQuoteContext(host=self.host, port=self.port)
            end = datetime.now(ET).date()
            start = end - timedelta(days=self.lookback_days)
            sector = infer_sector_etf(ticker)
            bars = self._history(
                context,
                f"US.{ticker}",
                start.isoformat(),
                end.isoformat(),
                RET_OK,
                KLType,
                AuType,
                KL_FIELD,
            )
            if len(bars) < MINIMUM_ANALYSIS_SESSIONS:
                raise StockMarketDataError("AXIS_STOCK_HISTORY_INSUFFICIENT")
            sector_bars = None
            benchmark_bars = None
            with suppress(StockMarketDataError):
                sector_bars = self._history(
                    context,
                    f"US.{sector}",
                    start.isoformat(),
                    end.isoformat(),
                    RET_OK,
                    KLType,
                    AuType,
                    KL_FIELD,
                )
            if sector == "SPY":
                benchmark_bars = sector_bars
            else:
                with suppress(StockMarketDataError):
                    benchmark_bars = self._history(
                        context,
                        "US.SPY",
                        start.isoformat(),
                        end.isoformat(),
                        RET_OK,
                        KLType,
                        AuType,
                        KL_FIELD,
                    )
            return StockMarketBundle(ticker, bars, sector, sector_bars, benchmark_bars)
        except StockMarketDataError:
            raise
        except Exception as exc:
            raise StockMarketDataError("MOOMOO_STOCK_HISTORY_FAILED") from exc
        finally:
            if context is not None:
                with suppress(Exception):
                    context.close()

    @staticmethod
    def _history(
        context: Any,
        code: str,
        start: str,
        end: str,
        ret_ok: int,
        kl_type: Any,
        au_type: Any,
        kl_field: Any,
    ) -> tuple[DailyBar, ...]:
        global _LAST_HISTORY_REQUEST_AT
        with _HISTORY_REQUEST_LOCK:
            elapsed = time.monotonic() - _LAST_HISTORY_REQUEST_AT
            if elapsed < _MINIMUM_HISTORY_INTERVAL_SECONDS:
                time.sleep(_MINIMUM_HISTORY_INTERVAL_SECONDS - elapsed)
            _LAST_HISTORY_REQUEST_AT = time.monotonic()
        ret, frame, _ = context.request_history_kline(
            code,
            start=start,
            end=end,
            ktype=kl_type.K_DAY,
            autype=au_type.QFQ,
            fields=[kl_field.ALL],
            max_count=1000,
        )
        if ret != ret_ok or not hasattr(frame, "iterrows"):
            raise StockMarketDataError("MOOMOO_STOCK_HISTORY_UNAVAILABLE")
        rows = []
        for _, item in frame.iterrows():
            try:
                timestamp = datetime.strptime(str(item["time_key"])[:10], "%Y-%m-%d").replace(
                    hour=16, tzinfo=ET
                )
                rows.append(
                    DailyBar(
                        timestamp=timestamp,
                        open=float(item["open"]),
                        high=float(item["high"]),
                        low=float(item["low"]),
                        close=float(item["close"]),
                        volume=float(item.get("volume") or 0),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        by_date = {bar.timestamp.date(): bar for bar in rows}
        return tuple(by_date[value] for value in sorted(by_date))
