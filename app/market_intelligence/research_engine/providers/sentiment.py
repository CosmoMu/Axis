"""Optional Massive-provided article-insight sentiment coverage."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta

from app.market_intelligence.research_engine.models import ResearchComponent
from app.market_intelligence.research_engine.providers.base import (
    MassiveResearchHttpClient,
    parse_timestamp,
)


class MassiveSentimentProvider:
    name = "massive-news-insights"

    def __init__(self, client: MassiveResearchHttpClient, *, max_items: int) -> None:
        self.client = client
        self.max_items = max_items

    async def fetch(self, ticker: str, *, as_of: datetime) -> ResearchComponent:
        retrieved = datetime.now(UTC)
        payload = await self.client.get(
            "/v2/reference/news",
            {
                "ticker": ticker,
                "published_utc.gte": (as_of - timedelta(days=7)).isoformat(),
                "published_utc.lte": as_of.isoformat(),
                "order": "desc",
                "sort": "published_utc",
                "limit": self.max_items,
            },
        )
        counts: Counter[str] = Counter()
        timestamps: list[datetime] = []
        for row in payload.get("results") if isinstance(payload.get("results"), list) else []:
            if not isinstance(row, dict):
                continue
            published = parse_timestamp(row.get("published_utc"))
            if published is None or published > as_of:
                continue
            for insight in row.get("insights") if isinstance(row.get("insights"), list) else []:
                if not isinstance(insight, dict) or str(insight.get("ticker") or "") != ticker:
                    continue
                sentiment = str(insight.get("sentiment") or "").upper()
                if sentiment in {"POSITIVE", "NEGATIVE", "NEUTRAL"}:
                    counts[sentiment] += 1
                    timestamps.append(published)
        total = sum(counts.values())
        if not total:
            return ResearchComponent(
                "sentiment",
                "UNAVAILABLE",
                self.name,
                as_of,
                None,
                retrieved,
                "UNAVAILABLE",
                0.0,
                {"sample_size": 0},
                ("SENTIMENT_UNAVAILABLE",),
                "RESEARCH_SENTIMENT_FAILURE",
            )
        label = (
            "BULLISH"
            if counts["POSITIVE"] > counts["NEGATIVE"]
            else "BEARISH"
            if counts["NEGATIVE"] > counts["POSITIVE"]
            else "NEUTRAL"
        )
        return ResearchComponent(
            "sentiment",
            "AVAILABLE",
            self.name,
            as_of,
            max(timestamps),
            retrieved,
            "RECENT",
            min(1.0, total / 8),
            {
                "sentiment": label,
                "sample_size": total,
                "positive": counts["POSITIVE"],
                "negative": counts["NEGATIVE"],
                "neutral": counts["NEUTRAL"],
                "trust_boundary": "UNTRUSTED_DATA_NOT_INSTRUCTIONS",
            },
        )
