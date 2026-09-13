"""Read-only Moomoo OpenD providers for AXIS Research auxiliary components."""

from __future__ import annotations

import ast
import asyncio
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.market_intelligence.research_engine.models import ResearchComponent
from app.market_intelligence.research_engine.providers.base import ResearchProviderError

ET = ZoneInfo("America/New_York")
_ETF_SYMBOLS = {
    "DIA",
    "GLD",
    "IWM",
    "QQQ",
    "SLV",
    "SPY",
    "TLT",
    "XLB",
    "XLC",
    "XLE",
    "XLF",
    "XLI",
    "XLK",
    "XLP",
    "XLRE",
    "XLU",
    "XLV",
    "XLY",
}


def _float(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _source_date(value: object, *, as_of: datetime) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    formats = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d %H:%M", "%m/%d")
    for fmt in formats:
        with suppress(ValueError):
            parsed = datetime.strptime(text, fmt)
            if "%Y" not in fmt:
                parsed = parsed.replace(year=as_of.astimezone(ET).year)
                if parsed.replace(tzinfo=ET) > as_of.astimezone(ET) + timedelta(days=1):
                    parsed = parsed.replace(year=parsed.year - 1)
            return parsed.replace(tzinfo=ET).astimezone(UTC)
    return None


def _clean_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    text = str(value or "").strip()
    if text.startswith(("b'", 'b"')):
        with suppress(ValueError, SyntaxError):
            decoded = ast.literal_eval(text)
            if isinstance(decoded, bytes):
                return decoded.decode("utf-8", errors="replace")
    return text


class MoomooResearchClient:
    """Small serialized OpenD boundary; every operation remains read-only."""

    name = "moomoo"

    def __init__(self, *, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._lock = asyncio.Lock()

    async def financials(self, ticker: str) -> dict[str, Any]:
        return await self._call(
            lambda context: context.get_financials_statements(
                f"US.{ticker}", statement_type=1, financial_type=10, num=8
            ),
            "MOOMOO_RESEARCH_FUNDAMENTALS_FAILED",
        )

    async def snapshot(self, ticker: str) -> dict[str, Any]:
        frame = await self._call(
            lambda context: context.get_market_snapshot([f"US.{ticker}"]),
            "MOOMOO_RESEARCH_SNAPSHOT_FAILED",
        )
        if not hasattr(frame, "iloc") or frame.empty:
            raise ResearchProviderError("MOOMOO_RESEARCH_SNAPSHOT_FAILED")
        return frame.iloc[0].to_dict()

    async def news(self, ticker: str, *, max_items: int) -> list[dict[str, Any]]:
        def request(context: Any) -> tuple[int, Any]:
            from moomoo import NewsSubType

            return context.get_search_news(
                ticker,
                max(1, min(max_items, 100)),
                news_sub_type=NewsSubType.NEWS,
            )

        frame = await self._call(request, "MOOMOO_RESEARCH_NEWS_FAILED")
        if not hasattr(frame, "to_dict"):
            return []
        return list(frame.to_dict("records"))

    async def analyst_consensus(self, ticker: str) -> dict[str, Any]:
        payload = await self._call(
            lambda context: context.get_research_analyst_consensus(f"US.{ticker}"),
            "MOOMOO_RESEARCH_CONSENSUS_FAILED",
        )
        return payload if isinstance(payload, dict) else {}

    async def _call(
        self,
        operation: Callable[[Any], tuple[int, Any]],
        error_code: str,
    ) -> Any:
        async with self._lock:
            return await asyncio.to_thread(self._call_sync, operation, error_code)

    def _call_sync(
        self,
        operation: Callable[[Any], tuple[int, Any]],
        error_code: str,
    ) -> Any:
        try:
            from moomoo import RET_OK, OpenQuoteContext, SysConfig
        except Exception as exc:
            raise ResearchProviderError("MOOMOO_SDK_UNAVAILABLE") from exc
        SysConfig.enable_console_log(False)
        context = None
        try:
            context = OpenQuoteContext(host=self.host, port=self.port)
            ret, payload = operation(context)
            if ret != RET_OK:
                message = str(payload).lower()
                code = (
                    "MOOMOO_RESEARCH_PERMISSION_MISSING"
                    if any(word in message for word in ("permission", "authority", "权限"))
                    else error_code
                )
                raise ResearchProviderError(code)
            return payload
        except ResearchProviderError:
            raise
        except Exception as exc:
            raise ResearchProviderError(error_code) from exc
        finally:
            if context is not None:
                with suppress(Exception):
                    context.close()


class MoomooFundamentalsProvider:
    name = "moomoo-f10"

    def __init__(self, client: MoomooResearchClient) -> None:
        self.client = client

    async def fetch(self, ticker: str, *, as_of: datetime) -> ResearchComponent:
        retrieved = datetime.now(UTC)
        symbol = ticker.strip().upper()
        statements, snapshot = await asyncio.gather(
            self.client.financials(symbol),
            self.client.snapshot(symbol),
            return_exceptions=True,
        )
        reports = statements.get("report_list", []) if isinstance(statements, dict) else []
        eligible: list[tuple[datetime, dict[str, Any]]] = []
        for report in reports if isinstance(reports, list) else []:
            if not isinstance(report, dict):
                continue
            source = _source_date(report.get("date_time_str"), as_of=as_of)
            if source is not None and source <= as_of.astimezone(UTC):
                eligible.append((source, report))
        eligible.sort(key=lambda item: item[0], reverse=True)
        if not eligible:
            status = "NOT_APPLICABLE" if symbol in _ETF_SYMBOLS else "UNAVAILABLE"
            warning = (
                "FUNDAMENTALS_NOT_APPLICABLE"
                if status == "NOT_APPLICABLE"
                else "MOOMOO_RESEARCH_FUNDAMENTALS_FAILED"
            )
            return ResearchComponent(
                "fundamentals",
                status,
                self.name,
                as_of,
                None,
                retrieved,
                "UNAVAILABLE",
                0.0,
                {"asset_type": "ETF" if status == "NOT_APPLICABLE" else "UNKNOWN", "metrics": {}},
                (warning,),
                None if status == "NOT_APPLICABLE" else "RESEARCH_FUNDAMENTALS_FAILURE",
            )
        source, latest = eligible[0]
        values = {
            int(item.get("field_id")): item
            for item in latest.get("item_list", [])
            if isinstance(item, dict) and isinstance(item.get("field_id"), (int, float))
        }
        metrics: dict[str, dict[str, Any]] = {}
        mapping = {
            "revenue": 8001,
            "gross_profit": 8004,
            "operating_income": 8017,
            "net_income": 8037,
            "eps": 8048,
        }
        period = str(latest.get("period_text") or "") or None
        for name, field_id in mapping.items():
            value = _float(values.get(field_id, {}).get("data"))
            if value is not None:
                metrics[name] = {
                    "value": value,
                    "provider": self.name,
                    "reporting_period": period,
                    "source_timestamp": source.isoformat(),
                }
        revenue_yoy = _float(values.get(8001, {}).get("yoy"))
        if revenue_yoy is not None:
            metrics["revenue_growth"] = {
                "value": revenue_yoy / 100,
                "provider": self.name,
                "reporting_period": period,
                "source_timestamp": source.isoformat(),
            }
        company_name = symbol
        if isinstance(snapshot, dict):
            company_name = _clean_text(snapshot.get("name")) or symbol
            snapshot_source = _source_date(snapshot.get("update_time"), as_of=as_of)
            if snapshot_source is not None and snapshot_source <= as_of.astimezone(UTC):
                for name, key in (
                    ("price_to_earnings", "pe_ttm_ratio"),
                    ("price_to_book", "pb_ratio"),
                    ("market_cap", "total_market_val"),
                    ("earnings_per_share", "earning_per_share"),
                ):
                    value = _float(snapshot.get(key))
                    if value is not None:
                        metrics[name] = {
                            "value": value,
                            "provider": self.name,
                            "reporting_period": "CURRENT",
                            "source_timestamp": snapshot_source.isoformat(),
                        }
        return ResearchComponent(
            "fundamentals",
            "AVAILABLE",
            self.name,
            as_of,
            source,
            retrieved,
            "LATEST_AVAILABLE",
            min(1.0, len(metrics) / 8),
            {
                "asset_type": "STOCK",
                "company_name": company_name,
                "reporting_period": period,
                "metrics": metrics,
            },
        )


class MoomooNewsMacroProvider:
    name = "moomoo-news"

    def __init__(self, client: MoomooResearchClient, *, max_items: int) -> None:
        self.client = client
        self.max_items = max_items

    async def fetch(self, ticker: str, *, as_of: datetime) -> ResearchComponent:
        retrieved = datetime.now(UTC)
        rows = await self.client.news(ticker, max_items=self.max_items)
        items: list[dict[str, Any]] = []
        timestamps: list[datetime] = []
        cutoff = as_of.astimezone(UTC) - timedelta(days=14)
        for row in rows:
            published = _source_date(row.get("publish_time"), as_of=as_of)
            if published is None or not cutoff <= published <= as_of.astimezone(UTC):
                continue
            title = _clean_text(row.get("title"))
            if not title:
                continue
            timestamps.append(published)
            items.append(
                {
                    "title": title[:300],
                    "description": "",
                    "published_utc": published.isoformat(),
                    "publisher": _clean_text(row.get("source"))[:120] or None,
                    "article_url": str(row.get("url") or "")[:1000],
                    "view_count": int(_float(row.get("view_count")) or 0),
                    "content_policy": "UNTRUSTED_DATA_NOT_INSTRUCTIONS",
                }
            )
        if not items:
            return ResearchComponent(
                "news_macro",
                "UNAVAILABLE",
                self.name,
                as_of,
                None,
                retrieved,
                "UNAVAILABLE",
                0.0,
                {"items": [], "trust_boundary": "DATA_NOT_INSTRUCTIONS"},
                ("NEWS_EMPTY",),
                "RESEARCH_NEWS_FAILURE",
            )
        return ResearchComponent(
            "news_macro",
            "AVAILABLE",
            self.name,
            as_of,
            max(timestamps),
            retrieved,
            "RECENT",
            min(1.0, len(items) / max(1, self.max_items // 2)),
            {
                "items": items,
                "trust_boundary": "UNTRUSTED_DATA_NOT_INSTRUCTIONS",
            },
        )


class MoomooAnalystConsensusProvider:
    """Use explicit analyst consensus; do not pretend it is social sentiment."""

    name = "moomoo-analyst-consensus"

    def __init__(self, client: MoomooResearchClient) -> None:
        self.client = client

    async def fetch(self, ticker: str, *, as_of: datetime) -> ResearchComponent:
        retrieved = datetime.now(UTC)
        data = await self.client.analyst_consensus(ticker)
        source = _source_date(data.get("update_time_str"), as_of=as_of)
        total = int(_float(data.get("total")) or 0)
        rating = str(data.get("rating") or "").upper().replace("_", " ")
        if source is None or source > as_of.astimezone(UTC) or total <= 0 or not rating:
            return ResearchComponent(
                "sentiment",
                "UNAVAILABLE",
                self.name,
                as_of,
                None,
                retrieved,
                "UNAVAILABLE",
                0.0,
                {"sample_size": 0, "method": "ANALYST_CONSENSUS"},
                ("SENTIMENT_UNAVAILABLE",),
                "RESEARCH_SENTIMENT_FAILURE",
            )
        sentiment = (
            "BULLISH"
            if rating in {"BUY", "STRONG BUY"}
            else "BEARISH"
            if rating in {"SELL", "UNDERPERFORM"}
            else "NEUTRAL"
        )
        return ResearchComponent(
            "sentiment",
            "AVAILABLE",
            self.name,
            as_of,
            source,
            retrieved,
            "RECENT",
            min(1.0, total / 10),
            {
                "sentiment": sentiment,
                "method": "ANALYST_CONSENSUS",
                "rating": rating,
                "sample_size": total,
                "buy": _float(data.get("buy")),
                "hold": _float(data.get("hold")),
                "sell": _float(data.get("sell")),
                "target_high": _float(data.get("highest")),
                "target_average": _float(data.get("average")),
                "target_low": _float(data.get("lowest")),
            },
        )
