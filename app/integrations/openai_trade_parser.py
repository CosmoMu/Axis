from __future__ import annotations

import base64
import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from openai import AsyncOpenAI


class TradeParseError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ParserAttachment:
    content_type: str
    data: bytes


@dataclass(frozen=True, slots=True)
class TradeParseResult:
    payload: dict[str, Any]
    response_id: str | None
    model: str


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
        model: str,
        timeout_seconds: int,
        max_retries: int,
        schema: dict[str, Any],
        prompt: str,
        client: Any | None = None,
    ) -> None:
        self.model = model
        self.schema = copy.deepcopy(schema)
        self.api_schema = _openai_schema(schema)
        self.prompt = prompt
        self.validator = Draft202012Validator(schema, format_checker=FormatChecker())
        self.client = client or AsyncOpenAI(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=max_retries,
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

        try:
            response = await self.client.responses.create(
                model=self.model,
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
                max_output_tokens=2500,
                store=False,
            )
        except Exception as exc:
            raise TradeParseError("LLM_REQUEST_FAILED") from exc

        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text.strip():
            raise TradeParseError("LLM_OUTPUT_EMPTY")
        try:
            payload = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise TradeParseError("LLM_OUTPUT_NOT_JSON") from exc
        if not isinstance(payload, dict):
            raise TradeParseError("LLM_OUTPUT_NOT_OBJECT")
        errors = list(self.validator.iter_errors(payload))
        if errors:
            raise TradeParseError("LLM_OUTPUT_SCHEMA_INVALID")

        response_id = getattr(response, "id", None)
        return TradeParseResult(
            payload=payload,
            response_id=response_id if isinstance(response_id, str) else None,
            model=self.model,
        )
