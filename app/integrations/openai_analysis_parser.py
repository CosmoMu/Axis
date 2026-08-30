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
from app.integrations.openai_trade_parser import LlmInvocationTrace, ParserAttachment


class AnalysisParseError(RuntimeError):
    def __init__(self, code: str, *, trace: LlmInvocationTrace | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.trace = trace


@dataclass(frozen=True, slots=True)
class AnalysisParseResult:
    payload: dict[str, Any]
    trace: LlmInvocationTrace


def load_analysis_schema(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(payload)
    except Exception as exc:
        raise AnalysisParseError("ANALYSIS_SCHEMA_INVALID") from exc
    if not isinstance(payload, dict):
        raise AnalysisParseError("ANALYSIS_SCHEMA_INVALID")
    return payload


def load_analysis_prompt(path: Path) -> str:
    try:
        prompt = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise AnalysisParseError("ANALYSIS_PROMPT_LOAD_FAILED") from exc
    if not prompt:
        raise AnalysisParseError("ANALYSIS_PROMPT_EMPTY")
    return prompt


def _api_schema(schema: dict[str, Any]) -> dict[str, Any]:
    unsupported = {
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
            return {key: sanitize(child) for key, child in value.items() if key not in unsupported}
        if isinstance(value, list):
            return [sanitize(child) for child in value]
        return value

    return sanitize(copy.deepcopy(schema))


class OpenAIAnalysisParser:
    def __init__(
        self,
        *,
        api_key: str,
        route: ModelRoute,
        schema: dict[str, Any],
        prompt: str,
        client: Any | None = None,
    ) -> None:
        if route.workload not in {
            LlmWorkload.ANALYSIS_PARSE,
            LlmWorkload.ANALYSIS_REWRITE,
        }:
            raise AnalysisParseError("ANALYSIS_WORKLOAD_INVALID")
        self.route = route
        self.schema = copy.deepcopy(schema)
        self.api_schema = _api_schema(schema)
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
        model = getattr(response, "model", None) if response is not None else None
        response_id = getattr(response, "id", None) if response is not None else None
        return LlmInvocationTrace(
            provider=self.route.provider,
            model=model if isinstance(model, str) and model else self.route.model,
            workload=self.route.workload,
            prompt_version=self.route.prompt_version,
            schema_version=self.route.schema_version,
            latency_ms=max(0, round((perf_counter() - started_at) * 1000)),
            success=success,
            error_type=error_type,
            response_id=response_id if isinstance(response_id, str) else None,
        )

    async def parse(
        self,
        *,
        raw_text: str | None,
        attachments: list[ParserAttachment],
        rewrite_instruction: str | None = None,
        current_payload: dict[str, Any] | None = None,
    ) -> AnalysisParseResult:
        content: list[dict[str, Any]] = [
            {
                "type": "input_text",
                "text": raw_text or "No text supplied. Use only visible image facts.",
            }
        ]
        if current_payload is not None:
            content.append(
                {
                    "type": "input_text",
                    "text": (
                        "Current normalized draft:\n"
                        + json.dumps(current_payload, ensure_ascii=False)
                        + "\nRewrite instruction: "
                        + (rewrite_instruction or "重新识别原文")
                    ),
                }
            )
        for attachment in attachments:
            content.append(
                {
                    "type": "input_image",
                    "image_url": (
                        f"data:{attachment.content_type};base64,"
                        + base64.b64encode(attachment.data).decode("ascii")
                    ),
                    "detail": "auto",
                }
            )
        started_at = perf_counter()
        response = None
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
                        "name": "axis_analysis_parse",
                        "strict": True,
                        "schema": self.api_schema,
                    }
                },
                reasoning={"effort": self.route.reasoning},
                max_output_tokens=3500,
                store=False,
            )
            output = getattr(response, "output_text", None)
            if not isinstance(output, str) or not output.strip():
                raise AnalysisParseError("ANALYSIS_OUTPUT_EMPTY")
            try:
                payload = json.loads(output)
            except json.JSONDecodeError as exc:
                raise AnalysisParseError("ANALYSIS_OUTPUT_SCHEMA_INVALID") from exc
            if not isinstance(payload, dict) or list(self.validator.iter_errors(payload)):
                raise AnalysisParseError("ANALYSIS_OUTPUT_SCHEMA_INVALID")
        except AnalysisParseError as exc:
            raise AnalysisParseError(
                exc.code,
                trace=self._trace(
                    started_at=started_at,
                    success=False,
                    error_type=exc.code,
                    response=response,
                ),
            ) from exc
        except Exception as exc:
            raise AnalysisParseError(
                "ANALYSIS_REQUEST_FAILED",
                trace=self._trace(
                    started_at=started_at,
                    success=False,
                    error_type="ANALYSIS_REQUEST_FAILED",
                    response=response,
                ),
            ) from exc
        return AnalysisParseResult(
            payload=payload,
            trace=self._trace(
                started_at=started_at,
                success=True,
                error_type=None,
                response=response,
            ),
        )
