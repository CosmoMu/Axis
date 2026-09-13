"""Shared safe HTTP plumbing for Massive research data."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import aiohttp


class ResearchProviderError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class MassiveResearchHttpClient:
    name = "massive"

    def __init__(self, *, api_key: str, base_url: str, timeout_seconds: int) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        safe_params = {**params, "apiKey": self.api_key}
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        try:
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.get(f"{self.base_url}{path}", params=safe_params) as response,
            ):
                if response.status in {401, 403}:
                    raise ResearchProviderError("MASSIVE_AUTH_FAILED")
                if response.status == 429:
                    raise ResearchProviderError("MASSIVE_RATE_LIMITED")
                if response.status >= 400:
                    raise ResearchProviderError("MASSIVE_RESEARCH_PROVIDER_FAILED")
                payload = await response.json(content_type=None)
        except ResearchProviderError:
            raise
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            raise ResearchProviderError("MASSIVE_RESEARCH_PROVIDER_FAILED") from exc
        if not isinstance(payload, dict):
            raise ResearchProviderError("MASSIVE_RESEARCH_RESPONSE_INVALID")
        return payload


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.fromisoformat(f"{value.strip()}T00:00:00+00:00")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def latest_not_after(rows: Any, as_of: datetime) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    valid: list[tuple[datetime, dict[str, Any]]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        timestamp = parse_timestamp(
            row.get("filing_date") or row.get("date") or row.get("period_end")
        )
        if timestamp is not None and timestamp <= as_of:
            valid.append((timestamp, row))
    valid.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in valid]
