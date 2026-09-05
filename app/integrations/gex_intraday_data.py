"""Read-only intraday market-data boundary for AXIS GEX Explorer."""

from __future__ import annotations

import asyncio
import math
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from app.market_intelligence.gex_explorer.models import GexIntradayBar

ET = ZoneInfo("America/New_York")


class GexIntradayDataError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class GexIntradayResult:
    ticker: str
    provider: str
    session_date: date
    source_timestamp: datetime
    bars: tuple[GexIntradayBar, ...]


class GexIntradayDataProvider(Protocol):
    name: str

    async def fetch(self, ticker: str, *, bar_count: int) -> GexIntradayResult: ...


class MoomooGexIntradayProvider:
    """Latest regular-session 1-minute candles through the local OpenD connection."""

    name = "moomoo"
    _INDEX_CODES = {
        "SPX": "US..SPX",
        "NDX": "US..NDX",
        "DJI": "US..DJI",
    }

    def __init__(self, *, host: str, port: int) -> None:
        self.host = host
        self.port = port

    async def fetch(self, ticker: str, *, bar_count: int) -> GexIntradayResult:
        if bar_count <= 0 or bar_count > 1000:
            raise GexIntradayDataError("GEX_INTRADAY_POLICY_INVALID")
        return await asyncio.to_thread(self._fetch_sync, ticker, bar_count)

    def _fetch_sync(self, ticker: str, bar_count: int) -> GexIntradayResult:
        try:
            from moomoo import RET_OK, AuType, KLType, OpenQuoteContext, SubType, SysConfig
        except Exception as exc:
            raise GexIntradayDataError("GEX_MOOMOO_SDK_UNAVAILABLE") from exc

        symbol = ticker.strip().upper().removeprefix("US.")
        if not symbol:
            raise GexIntradayDataError("GEX_INTRADAY_TICKER_INVALID")
        code = self._INDEX_CODES.get(symbol, f"US.{symbol}")
        SysConfig.enable_console_log(False)
        context = None
        try:
            context = OpenQuoteContext(host=self.host, port=self.port)
            ret, message = context.subscribe([code], [SubType.K_1M])
            if ret != RET_OK:
                raise GexIntradayDataError("GEX_INTRADAY_SUBSCRIPTION_FAILED")
            ret, frame = context.get_cur_kline(
                code,
                1000,
                KLType.K_1M,
                AuType.QFQ,
            )
            if ret != RET_OK or not hasattr(frame, "iterrows"):
                raise GexIntradayDataError("GEX_INTRADAY_UNAVAILABLE")
            bars = self._normalize(frame)
            if not bars:
                raise GexIntradayDataError("GEX_INTRADAY_EMPTY")
            session_date = max(item.timestamp_et.date() for item in bars)
            session = tuple(
                item for item in bars if item.timestamp_et.date() == session_date
            )[-bar_count:]
            if not session:
                raise GexIntradayDataError("GEX_INTRADAY_EMPTY")
            return GexIntradayResult(
                ticker=symbol,
                provider=self.name,
                session_date=session_date,
                source_timestamp=session[-1].timestamp_et,
                bars=session,
            )
        except GexIntradayDataError:
            raise
        except Exception as exc:
            raise GexIntradayDataError("GEX_INTRADAY_UNAVAILABLE") from exc
        finally:
            if context is not None:
                with suppress(Exception):
                    context.close()

    @staticmethod
    def _normalize(frame: Any) -> tuple[GexIntradayBar, ...]:
        rows: list[GexIntradayBar] = []
        for _, item in frame.iterrows():
            try:
                timestamp = datetime.strptime(
                    str(item["time_key"])[:19], "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=ET)
                if not time(9, 30) <= timestamp.time() <= time(16, 0):
                    continue
                volume = float(item.get("volume") or 0)
                rows.append(
                    GexIntradayBar(
                        timestamp_et=timestamp,
                        open=float(item["open"]),
                        high=float(item["high"]),
                        low=float(item["low"]),
                        close=float(item["close"]),
                        volume=volume if math.isfinite(volume) and volume >= 0 else 0,
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        by_timestamp = {item.timestamp_et: item for item in rows}
        return tuple(by_timestamp[value] for value in sorted(by_timestamp))
