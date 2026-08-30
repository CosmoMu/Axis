from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domain.enums import LlmWorkload
from app.integrations.model_router import ModelRouter
from app.integrations.openai_analysis_parser import (
    AnalysisParseError,
    OpenAIAnalysisParser,
    load_analysis_prompt,
    load_analysis_schema,
)
from app.integrations.openai_trade_parser import ParserAttachment

ROOT = Path(__file__).resolve().parents[1]


def valid_analysis_payload(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "analysis_type": "TICKER",
        "symbols": ["NVDA"],
        "sector": "Semiconductors",
        "stance": "BULLISH",
        "time_horizon": "SWING",
        "title": "NVDA 观察",
        "summary": "价格正在测试图中明确标注的区域。",
        "core_thesis": "仅观察原图中出现的趋势与位置。",
        "why_now": ["输入指出价格正在测试关键区域"],
        "supporting_points": ["原图显示价格维持在支撑上方"],
        "engine_observations": [],
        "key_levels": [
            {
                "symbol": "NVDA",
                "level_type": "WATCH",
                "price": None,
                "note": "原文未提供明确价格",
                "source": "INPUT",
            }
        ],
        "invalidation": None,
        "catalysts": [],
        "risks": ["方向仍需确认"],
        "market_conditions": [],
        "related_symbols": ["SMH"],
        "source_projection": {
            "present": False,
            "attachment_index": None,
            "evidence": None,
            "path_points": [],
        },
        "confidence": 0.82,
        "missing_fields": ["explicit_price"],
        "warnings": [],
    }
    payload.update(updates)
    return payload


class FakeResponses:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.kwargs: dict[str, object] | None = None

    async def create(self, **kwargs: object) -> SimpleNamespace:
        self.kwargs = kwargs
        output = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return SimpleNamespace(id="resp_analysis", model="gpt-5.6-terra", output_text=output)


class FakeClient:
    def __init__(self, responses: FakeResponses) -> None:
        self.responses = responses


def parser(responses: FakeResponses, workload: LlmWorkload) -> OpenAIAnalysisParser:
    route = ModelRouter.load(ROOT / "config" / "model_routing.yaml").resolve(workload)
    return OpenAIAnalysisParser(
        api_key="test-only-placeholder",
        route=route,
        schema=load_analysis_schema(ROOT / "config" / "llm_analysis_schema.json"),
        prompt=load_analysis_prompt(ROOT / "config" / "llm_analysis_prompt.txt"),
        client=FakeClient(responses),
    )


@pytest.mark.asyncio
async def test_analysis_parser_uses_strict_schema_and_multiple_images() -> None:
    responses = FakeResponses(valid_analysis_payload())
    result = await parser(responses, LlmWorkload.ANALYSIS_PARSE).parse(
        raw_text="NVDA 图表观点",
        attachments=[
            ParserAttachment("image/png", b"first-image"),
            ParserAttachment("image/jpeg", b"second-image"),
        ],
    )

    assert result.payload["symbols"] == ["NVDA"]
    assert result.payload["key_levels"][0]["price"] is None  # type: ignore[index]
    assert result.trace.workload is LlmWorkload.ANALYSIS_PARSE
    assert result.trace.prompt_version == "axis-analysis-parse-v5"
    assert result.trace.schema_version == "axis-analysis-v4"
    assert responses.kwargs is not None
    assert responses.kwargs["store"] is False
    assert responses.kwargs["reasoning"] == {"effort": "medium"}
    text_format = responses.kwargs["text"]["format"]  # type: ignore[index]
    assert text_format["strict"] is True
    assert text_format["type"] == "json_schema"
    api_schema = text_format["schema"]
    assert "title" in api_schema["properties"]
    assert set(api_schema["required"]) == set(api_schema["properties"])
    content = responses.kwargs["input"][1]["content"]  # type: ignore[index]
    assert [item["type"] for item in content] == [
        "input_text",
        "input_image",
        "input_image",
    ]
    assert content[1]["image_url"].startswith("data:image/png;base64,")
    assert content[2]["image_url"].startswith("data:image/jpeg;base64,")
    assert result.payload["source_projection"]["present"] is False  # type: ignore[index]
    assert result.payload["source_projection"]["path_points"] == []  # type: ignore[index]


@pytest.mark.asyncio
async def test_analysis_rewrite_preserves_explicit_revision_context() -> None:
    responses = FakeResponses(valid_analysis_payload(summary="更简洁的观点。"))
    current = valid_analysis_payload()
    result = await parser(responses, LlmWorkload.ANALYSIS_REWRITE).parse(
        raw_text="NVDA 图表观点",
        attachments=[],
        rewrite_instruction="更简洁",
        current_payload=current,
    )

    assert result.trace.workload is LlmWorkload.ANALYSIS_REWRITE
    assert responses.kwargs is not None
    content = responses.kwargs["input"][1]["content"]  # type: ignore[index]
    assert "Current normalized draft" in content[1]["text"]
    assert "更简洁" in content[1]["text"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_output",
    ["not-json", valid_analysis_payload(analysis_type="INVALID")],
)
async def test_analysis_parser_rejects_malformed_output_with_safe_code(
    invalid_output: object,
) -> None:
    with pytest.raises(AnalysisParseError) as caught:
        await parser(FakeResponses(invalid_output), LlmWorkload.ANALYSIS_PARSE).parse(
            raw_text="private analysis",
            attachments=[],
        )

    assert str(caught.value) == "ANALYSIS_OUTPUT_SCHEMA_INVALID"
    assert caught.value.trace is not None
    assert caught.value.trace.success is False


def test_analysis_prompt_forbids_invention_and_trade_instructions() -> None:
    prompt = load_analysis_prompt(ROOT / "config" / "llm_analysis_prompt.txt")

    assert "Never invent" in prompt
    assert "explicitly visible" in prompt
    assert "Do not create Entry, TP, SL, position, or order instructions" in prompt
    assert "ordered future price path" in prompt
    assert "never infer a missing numeric price" in prompt
    assert "why_now" in prompt
    assert "engine_observations must always be an empty array" in prompt
