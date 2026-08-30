from __future__ import annotations

import base64
import copy
import json
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from openai import AsyncOpenAI

from app.domain.enums import LlmWorkload
from app.integrations.model_router import ModelRoute


@dataclass(frozen=True, slots=True)
class ParserAttachment:
    content_type: str
    data: bytes


@dataclass(frozen=True, slots=True)
class LlmInvocationTrace:
    provider: str
    model: str
    workload: LlmWorkload
    prompt_version: str
    schema_version: str
    latency_ms: int
    success: bool
    error_type: str | None
    response_id: str | None


class TradeParseError(RuntimeError):
    def __init__(self, code: str, *, trace: LlmInvocationTrace | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.trace = trace


@dataclass(frozen=True, slots=True)
class TradeParseResult:
    payload: dict[str, Any]
    trace: LlmInvocationTrace

    @property
    def response_id(self) -> str | None:
        return self.trace.response_id

    @property
    def model(self) -> str:
        return self.trace.model


def load_trade_schema(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TradeParseError("LLM_SCHEMA_LOAD_FAILED") from exc
    if not isinstance(payload, dict):
        raise TradeParseError("LLM_SCHEMA_INVALID")
    try:
        Draft202012Validator.check_schema(payload)
    except Exception as exc:
        raise TradeParseError("LLM_SCHEMA_INVALID") from exc
    return payload


def load_trade_prompt(path: Path) -> str:
    try:
        prompt = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise TradeParseError("LLM_PROMPT_LOAD_FAILED") from exc
    if not prompt:
        raise TradeParseError("LLM_PROMPT_EMPTY")
    return prompt


def _openai_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return the documented Structured Outputs subset; full checks still run locally."""

    unsupported_or_annotation = {
        "$schema",
        "title",
        "description",
        "default",
        "examples",
        "maxLength",
        "minLength",
        "uniqueItems",
    }

    def sanitize(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: sanitize(child)
                for key, child in value.items()
                if key not in unsupported_or_annotation
            }
        if isinstance(value, list):
            return [sanitize(child) for child in value]
        return value

    return sanitize(copy.deepcopy(schema))


class OpenAITradeParser:
    def __init__(
        self,
        *,
        api_key: str,
        route: ModelRoute,
        schema: dict[str, Any],
        prompt: str,
        client: Any | None = None,
    ) -> None:
        if route.workload is not LlmWorkload.SIGNAL_PARSE:
            raise TradeParseError("LLM_WORKLOAD_INVALID")
        self.route = route
        self.schema = copy.deepcopy(schema)
        self.api_schema = _openai_schema(schema)
        self.prompt = prompt
        self.validator = Draft202012Validator(schema, format_checker=FormatChecker())
        self.client = client or AsyncOpenAI(
            api_key=api_key,
            timeout=route.timeout_seconds,
            max_retries=route.max_retries,
        )

    def _trace(
        self,
        *,
        started_at: float,
        success: bool,
        error_type: str | None,
        response: Any | None,
    ) -> LlmInvocationTrace:
        response_model = getattr(response, "model", None) if response is not None else None
        response_id = getattr(response, "id", None) if response is not None else None
        return LlmInvocationTrace(
            provider=self.route.provider,
            model=(
                response_model
                if isinstance(response_model, str) and response_model
                else self.route.model
            ),
            workload=self.route.workload,
            prompt_version=self.route.prompt_version,
            schema_version=self.route.schema_version,
            latency_ms=max(0, round((perf_counter() - started_at) * 1000)),
            success=success,
            error_type=error_type,
            response_id=response_id if isinstance(response_id, str) else None,
        )

    def _parse_error(
        self,
        code: str,
        *,
        started_at: float,
        response: Any | None,
    ) -> TradeParseError:
        return TradeParseError(
            code,
            trace=self._trace(
                started_at=started_at,
                success=False,
                error_type=code,
                response=response,
            ),
        )

    async def parse(
        self,
        *,
        raw_text: str | None,
        attachments: list[ParserAttachment],
    ) -> TradeParseResult:
        content: list[dict[str, Any]] = [
            {
                "type": "input_text",
                "text": raw_text or "No text was supplied. Extract only visible image facts.",
            }
        ]
        for attachment in attachments:
            encoded = base64.b64encode(attachment.data).decode("ascii")
            content.append(
                {
                    "type": "input_image",
                    "image_url": f"data:{attachment.content_type};base64,{encoded}",
                    "detail": "auto",
                }
            )

        started_at = perf_counter()
        try:
            response = await self.client.responses.create(
                model=self.route.model,
                input=[
                    {"role": "system", "content": self.prompt},
                    {"role": "user", "content": content},
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "axis_trade_parse",
                        "strict": True,
                        "schema": self.api_schema,
                    }
                },
                reasoning={"effort": self.route.reasoning},
                max_output_tokens=2500,
                store=False,
            )
        except Exception as exc:
            raise self._parse_error(
                "LLM_REQUEST_FAILED",
                started_at=started_at,
                response=None,
            ) from exc

        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text.strip():
            raise self._parse_error(
                "LLM_OUTPUT_EMPTY",
                started_at=started_at,
                response=response,
            )
        try:
            payload = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise self._parse_error(
                "LLM_OUTPUT_NOT_JSON",
                started_at=started_at,
                response=response,
            ) from exc
        if not isinstance(payload, dict):
            raise self._parse_error(
                "LLM_OUTPUT_NOT_OBJECT",
                started_at=started_at,
                response=response,
            )
        errors = list(self.validator.iter_errors(payload))
        if errors:
            raise self._parse_error(
                "LLM_OUTPUT_SCHEMA_INVALID",
                started_at=started_at,
                response=response,
            )

        return TradeParseResult(
            payload=payload,
            trace=self._trace(
                started_at=started_at,
                success=True,
                error_type=None,
                response=response,
            ),
        )
