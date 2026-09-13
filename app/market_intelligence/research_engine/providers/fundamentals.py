"""Point-in-time-safe Massive fundamentals provider."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from app.market_intelligence.research_engine.models import ResearchComponent
from app.market_intelligence.research_engine.providers.base import (
    MassiveResearchHttpClient,
    ResearchProviderError,
    latest_not_after,
    parse_timestamp,
)


def _metric(
    value: Any,
    *,
    period: str | None,
    source_timestamp: datetime | None,
) -> dict[str, Any] | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return {
        "value": float(value),
        "provider": "massive",
        "reporting_period": period,
        "source_timestamp": source_timestamp.isoformat() if source_timestamp else None,
    }


class MassiveFundamentalsProvider:
    name = "massive"

    def __init__(self, client: MassiveResearchHttpClient) -> None:
        self.client = client

    async def fetch(self, ticker: str, *, as_of: datetime) -> ResearchComponent:
        retrieved = datetime.now(UTC)
        params = {
            "ticker": ticker,
            "limit": 5,
            "sort": "filing_date.desc",
            "filing_date.lte": as_of.date().isoformat(),
        }
        try:
            (
                details_result,
                income_result,
                ratios_result,
                balance_result,
                cash_result,
            ) = await asyncio.gather(
                self.client.get(
                    f"/v3/reference/tickers/{ticker}",
                    {"date": as_of.date().isoformat()},
                ),
                self.client.get("/stocks/financials/v1/income-statements", params),
                self.client.get(
                    "/stocks/financials/v1/ratios",
                    {
                        "ticker": ticker,
                        "limit": 5,
                        "sort": "date.desc",
                        "date.lte": as_of.date().isoformat(),
                    },
                ),
                self.client.get("/stocks/financials/v1/balance-sheets", params),
                self.client.get("/stocks/financials/v1/cash-flow-statements", params),
                return_exceptions=True,
            )
        except Exception as exc:
            raise ResearchProviderError("RESEARCH_FUNDAMENTALS_FAILURE") from exc

        details = details_result.get("results", {}) if isinstance(details_result, dict) else {}
        asset_type = str(details.get("type") or "").upper() if isinstance(details, dict) else ""
        if asset_type in {"ETF", "INDEX", "ETV", "FUND"}:
            return ResearchComponent(
                "fundamentals",
                "NOT_APPLICABLE",
                self.name,
                as_of,
                None,
                retrieved,
                "LATEST_AVAILABLE",
                0.0,
                {"asset_type": asset_type, "reason": "FUNDAMENTALS_NOT_APPLICABLE"},
                ("FUNDAMENTALS_NOT_APPLICABLE",),
            )

        income = latest_not_after(
            income_result.get("results") if isinstance(income_result, dict) else None, as_of
        )
        ratios = latest_not_after(
            ratios_result.get("results") if isinstance(ratios_result, dict) else None, as_of
        )
        balances = latest_not_after(
            balance_result.get("results") if isinstance(balance_result, dict) else None, as_of
        )
        cash_flows = latest_not_after(
            cash_result.get("results") if isinstance(cash_result, dict) else None, as_of
        )
        latest_income = income[0] if income else {}
        latest_ratio = ratios[0] if ratios else {}
        latest_balance = balances[0] if balances else {}
        latest_cash = cash_flows[0] if cash_flows else {}
        source = max(
            (
                timestamp
                for timestamp in (
                    parse_timestamp(latest_income.get("filing_date")),
                    parse_timestamp(latest_ratio.get("date")),
                    parse_timestamp(latest_balance.get("filing_date")),
                    parse_timestamp(latest_cash.get("filing_date")),
                )
                if timestamp is not None
            ),
            default=None,
        )
        period = (
            str(
                latest_income.get("period_end")
                or latest_balance.get("period_end")
                or latest_cash.get("period_end")
                or ""
            )
            or None
        )
        metrics: dict[str, Any] = {}
        field_map = {
            "revenue": (latest_income, "revenue"),
            "eps": (latest_income, "diluted_earnings_per_share"),
            "gross_profit": (latest_income, "gross_profit"),
            "operating_income": (latest_income, "operating_income"),
            "net_income": (latest_income, "consolidated_net_income_loss"),
            "price_to_earnings": (latest_ratio, "price_to_earnings"),
            "price_to_sales": (latest_ratio, "price_to_sales"),
            "debt_to_equity": (latest_ratio, "debt_to_equity"),
            "free_cash_flow": (latest_ratio, "free_cash_flow"),
            "cash_and_equivalents": (latest_balance, "cash_and_equivalents"),
            "total_assets": (latest_balance, "total_assets"),
            "total_liabilities": (latest_balance, "total_liabilities"),
            "operating_cash_flow": (latest_cash, "net_cash_from_operating_activities"),
        }
        for name, (row, key) in field_map.items():
            value = _metric(row.get(key), period=period, source_timestamp=source)
            if value is not None:
                metrics[name] = value
        if len(income) >= 2:
            current_revenue = income[0].get("revenue")
            prior_revenue = income[1].get("revenue")
            if all(
                isinstance(item, (int, float)) for item in (current_revenue, prior_revenue)
            ) and (prior_revenue):
                metrics["revenue_growth"] = _metric(
                    (current_revenue / prior_revenue) - 1,
                    period=period,
                    source_timestamp=source,
                )
        if not metrics:
            errors = [
                item.code
                for item in (income_result, ratios_result, balance_result, cash_result)
                if isinstance(item, ResearchProviderError)
            ]
            return ResearchComponent(
                "fundamentals",
                "UNAVAILABLE",
                self.name,
                as_of,
                None,
                retrieved,
                "UNAVAILABLE",
                0.0,
                {"asset_type": asset_type or "UNKNOWN", "metrics": {}},
                tuple(errors or ["FUNDAMENTALS_EMPTY"]),
                "RESEARCH_FUNDAMENTALS_FAILURE",
            )
        return ResearchComponent(
            "fundamentals",
            "AVAILABLE",
            self.name,
            as_of,
            source,
            retrieved,
            "LATEST_AVAILABLE",
            min(1.0, len(metrics) / 10),
            {
                "asset_type": asset_type or "STOCK",
                "company_name": details.get("name") if isinstance(details, dict) else None,
                "metrics": metrics,
            },
        )
