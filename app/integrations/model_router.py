from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.domain.enums import LlmWorkload

ALLOWED_REASONING_EFFORTS = {"none", "low", "medium", "high", "xhigh", "max"}


class ModelRoutingError(RuntimeError):
    """Raised when workload routing configuration is absent or unsafe."""


@dataclass(frozen=True, slots=True)
class ModelRoute:
    provider: str
    api: str
    workload: LlmWorkload
    model: str
    reasoning: str
    prompt_version: str
    schema_version: str
    structured_output: Path | None
    timeout_seconds: int
    max_retries: int


def _mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ModelRoutingError(f"{context} 必须是 YAML mapping。")
    return value


def _positive_int(value: Any, context: str, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool):
        raise ModelRoutingError(f"{context} 必须是整数。")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ModelRoutingError(f"{context} 必须是整数。") from exc
    lower_bound = 0 if allow_zero else 1
    if parsed < lower_bound:
        comparator = "非负" if allow_zero else "正"
        raise ModelRoutingError(f"{context} 必须是{comparator}整数。")
    return parsed


class ModelRouter:
    def __init__(self, routes: Mapping[LlmWorkload, ModelRoute]) -> None:
        self._routes = dict(routes)
        missing = set(LlmWorkload) - set(self._routes)
        if missing:
            names = ", ".join(sorted(item.value for item in missing))
            raise ModelRoutingError(f"缺少 workload route：{names}。")

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        model_overrides: Mapping[LlmWorkload, str | None] | None = None,
        default_model_override: str | None = None,
        timeout_seconds_override: int | None = None,
        max_retries_override: int | None = None,
    ) -> ModelRouter:
        try:
            raw = _mapping(yaml.safe_load(path.read_text(encoding="utf-8")), "model routing")
        except OSError as exc:
            raise ModelRoutingError("无法读取 LLM routing config。") from exc

        provider = str(raw.get("provider", "")).strip().lower()
        api = str(raw.get("api", "")).strip().lower()
        if provider != "openai" or api != "responses":
            raise ModelRoutingError("当前只支持 openai / responses routing。")

        defaults = _mapping(raw.get("defaults"), "defaults")
        default_model = (default_model_override or str(defaults.get("model", ""))).strip()
        if not default_model:
            raise ModelRoutingError("defaults.model 不能为空。")
        timeout_seconds = (
            timeout_seconds_override
            if timeout_seconds_override is not None
            else _positive_int(defaults.get("timeout_seconds"), "defaults.timeout_seconds")
        )
        max_retries = (
            max_retries_override
            if max_retries_override is not None
            else _positive_int(
                defaults.get("max_retries"),
                "defaults.max_retries",
                allow_zero=True,
            )
        )
        timeout_seconds = _positive_int(timeout_seconds, "timeout_seconds override")
        max_retries = _positive_int(
            max_retries,
            "max_retries override",
            allow_zero=True,
        )

        workload_config = _mapping(raw.get("workloads"), "workloads")
        overrides = model_overrides or {}
        routes: dict[LlmWorkload, ModelRoute] = {}
        for workload in LlmWorkload:
            item = _mapping(workload_config.get(workload.value), f"workloads.{workload.value}")
            model = (overrides.get(workload) or str(item.get("model") or default_model)).strip()
            reasoning = str(item.get("reasoning", "medium")).strip().lower()
            prompt_version = str(item.get("prompt_version", "")).strip()
            schema_version = str(item.get("schema_version", "")).strip()
            if not model:
                raise ModelRoutingError(f"{workload.value}.model 不能为空。")
            if reasoning not in ALLOWED_REASONING_EFFORTS:
                raise ModelRoutingError(f"{workload.value}.reasoning 无效。")
            if not prompt_version or not schema_version:
                raise ModelRoutingError(
                    f"{workload.value} 必须配置 prompt_version 和 schema_version。"
                )
            structured_name = item.get("structured_output")
            structured_output = (
                (path.parent / str(structured_name)).resolve() if structured_name else None
            )
            if structured_output is not None and not structured_output.is_file():
                raise ModelRoutingError(
                    f"{workload.value}.structured_output 文件不存在。"
                )
            routes[workload] = ModelRoute(
                provider=provider,
                api=api,
                workload=workload,
                model=model,
                reasoning=reasoning,
                prompt_version=prompt_version,
                schema_version=schema_version,
                structured_output=structured_output,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
            )
        return cls(routes)

    def resolve(self, workload: LlmWorkload | str) -> ModelRoute:
        try:
            normalized = (
                workload if isinstance(workload, LlmWorkload) else LlmWorkload(str(workload))
            )
        except ValueError as exc:
            raise ModelRoutingError(f"未知 LLM workload：{workload}。") from exc
        return self._routes[normalized]
