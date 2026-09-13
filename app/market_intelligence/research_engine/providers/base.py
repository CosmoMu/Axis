"""Shared safe HTTP plumbing for Massive research data."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import aiohttp

from app.integrations.massive_market_data import verified_ssl_context


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
        self._request_lock = asyncio.Lock()

    async def get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        safe_params = {**params, "apiKey": self.api_key}
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        async with self._request_lock:
            for attempt in range(3):
                retry_delay = 0.0
                try:
                    connector = aiohttp.TCPConnector(ssl=verified_ssl_context())
                    async with (
                        aiohttp.ClientSession(timeout=timeout, connector=connector) as session,
                        session.get(f"{self.base_url}{path}", params=safe_params) as response,
                    ):
                        if response.status == 401:
                            raise ResearchProviderError("MASSIVE_AUTH_FAILED")
                        if response.status == 403:
                            raise ResearchProviderError("MASSIVE_ENTITLEMENT_REQUIRED")
                        if response.status == 429:
                            if attempt == 2:
                                raise ResearchProviderError("MASSIVE_RATE_LIMITED")
                            retry_delay = self._retry_delay(
                                response.headers.get("Retry-After"), attempt
                            )
                        elif response.status >= 400:
                            raise ResearchProviderError("MASSIVE_RESEARCH_PROVIDER_FAILED")
                        else:
                            payload = await response.json(content_type=None)
                            if not isinstance(payload, dict):
                                raise ResearchProviderError("MASSIVE_RESEARCH_RESPONSE_INVALID")
                            return payload
                except ResearchProviderError:
                    raise
                except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
                    raise ResearchProviderError("MASSIVE_RESEARCH_PROVIDER_FAILED") from exc
                await asyncio.sleep(retry_delay)
        raise ResearchProviderError("MASSIVE_RATE_LIMITED")

    @staticmethod
    def _retry_delay(header: str | None, attempt: int) -> float:
        try:
            requested = float(header) if header is not None else 0.0
        except ValueError:
            requested = 0.0
        return min(5.0, max(requested, float(2**attempt)))


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
