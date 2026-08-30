from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.integrations.openai_trade_parser import (
    OpenAITradeParser,
    ParserAttachment,
    TradeParseError,
    load_trade_prompt,
    load_trade_schema,
)

ROOT = Path(__file__).resolve().parents[1]


def valid_payload() -> dict[str, object]:
    return {
        "intent": "NEW_TRADE",
        "action": "ENTRY",
        "add_stage": "NONE",
        "ticker": "SPY",
        "expiry": "2026-09-18",
        "strike": 700,
        "option_side": "CALL",
        "entry_low": 1.2,
        "entry_high": 1.3,
        "action_price": None,
        "avg_cost": None,
        "sl": 0.8,
        "tp1": 1.6,
        "tp2": 2.0,
        "position_delta_eighths": None,
        "position_after_eighths": None,
        "current_pnl_pct": None,
        "category_suggestion": "SHORT_TERM",
        "mentor_hint": None,
        "confidence": 0.93,
        "missing_fields": [],
        "warnings": [],
        "summary": "SPY 短线新仓草稿。",
    }


class FakeResponses:
    def __init__(self, payload: dict[str, object] | None = None, error: Exception | None = None):
        self.payload = payload
        self.error = error
        self.kwargs: dict[str, object] | None = None

    async def create(self, **kwargs: object) -> SimpleNamespace:
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            id="resp_test",
            output_text=json.dumps(self.payload),
        )


class FakeClient:
    def __init__(self, responses: FakeResponses) -> None:
        self.responses = responses


def parser(responses: FakeResponses) -> OpenAITradeParser:
    return OpenAITradeParser(
        api_key="test-only-placeholder",
        model="gpt-5.6-terra",
        timeout_seconds=45,
        max_retries=2,
        schema=load_trade_schema(ROOT / "config" / "llm_trade_schema.json"),
        prompt=load_trade_prompt(ROOT / "config" / "llm_trade_prompt.txt"),
        client=FakeClient(responses),
    )


@pytest.mark.asyncio
async def test_parser_uses_strict_responses_schema_and_multimodal_input() -> None:
    responses = FakeResponses(valid_payload())
    result = await parser(responses).parse(
        raw_text="SPY 700C entry 1.20-1.30",
        attachments=[ParserAttachment("image/png", b"\x89PNG\r\n\x1a\naxis")],
    )

    assert result.payload["ticker"] == "SPY"
    assert result.response_id == "resp_test"
    assert responses.kwargs is not None
    assert responses.kwargs["store"] is False
    text_format = responses.kwargs["text"]["format"]  # type: ignore[index]
    assert text_format["strict"] is True
    assert text_format["type"] == "json_schema"
    schema = text_format["schema"]
    assert "$schema" not in schema
    assert "uniqueItems" not in schema["properties"]["missing_fields"]
    user_content = responses.kwargs["input"][1]["content"]  # type: ignore[index]
    assert user_content[1]["type"] == "input_image"
    assert user_content[1]["image_url"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_parser_exposes_only_safe_error_code() -> None:
    responses = FakeResponses(error=RuntimeError("sensitive upstream detail"))
    with pytest.raises(TradeParseError) as caught:
        await parser(responses).parse(raw_text="private signal", attachments=[])
    assert str(caught.value) == "LLM_REQUEST_FAILED"
    assert "sensitive" not in str(caught.value)
