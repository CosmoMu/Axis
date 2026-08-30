from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class CosmosStockAnalystError(RuntimeError):
    """A safe, secret-free failure from the local Cosmos analyst bridge."""


@dataclass(frozen=True, slots=True)
class CosmosStockAnalystResult:
    context: dict[str, Any]
    chart_png: bytes | None


class CosmosStockAnalystClient:
    _symbol = re.compile(r"^[A-Z0-9.\-]{1,12}$")
    _marker = "AXIS_COSMOS_JSON:"

    def __init__(
        self,
        *,
        runtime_root: Path,
        bridge_script: Path,
        python_path: Path | None = None,
        timeout_seconds: int = 180,
        max_chart_bytes: int = 10 * 1024 * 1024,
    ) -> None:
        self.runtime_root = runtime_root.resolve()
        self.bridge_script = bridge_script.resolve()
        self.python_path = (python_path or self.runtime_root / ".venv/bin/python").resolve()
        self.timeout_seconds = timeout_seconds
        self.max_chart_bytes = max_chart_bytes

    async def query(
        self, symbol: str, *, include_chart: bool = True
    ) -> CosmosStockAnalystResult:
        normalized = symbol.strip().upper()
        if not self._symbol.fullmatch(normalized):
            raise CosmosStockAnalystError("COSMOS_SYMBOL_INVALID")
        if not self.runtime_root.is_dir() or not self.python_path.is_file():
            raise CosmosStockAnalystError("COSMOS_RUNTIME_UNAVAILABLE")
        if not self.bridge_script.is_file():
            raise CosmosStockAnalystError("COSMOS_BRIDGE_UNAVAILABLE")

        safe_env = {
            name: value
            for name in ("PATH", "LANG", "LC_ALL", "SSL_CERT_FILE")
            if (value := os.environ.get(name))
        }
        try:
            arguments = [
                str(self.python_path),
                str(self.bridge_script),
                "--runtime-root",
                str(self.runtime_root),
                "--ticker",
                normalized,
            ]
            if not include_chart:
                arguments.append("--no-chart")
            process = await asyncio.create_subprocess_exec(
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=self.runtime_root,
                env=safe_env,
            )
            stdout, _ = await asyncio.wait_for(
                process.communicate(), timeout=self.timeout_seconds
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise CosmosStockAnalystError("COSMOS_QUERY_TIMEOUT") from exc
        except OSError as exc:
            raise CosmosStockAnalystError("COSMOS_QUERY_START_FAILED") from exc
        if process.returncode != 0:
            raise CosmosStockAnalystError("COSMOS_QUERY_FAILED")

        payload = None
        for line in stdout.decode("utf-8", errors="replace").splitlines():
            if line.startswith(self._marker):
                try:
                    payload = json.loads(line.removeprefix(self._marker))
                except json.JSONDecodeError as exc:
                    raise CosmosStockAnalystError("COSMOS_RESPONSE_INVALID") from exc
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise CosmosStockAnalystError("COSMOS_RESPONSE_INVALID")
        context = payload.get("analysis")
        raw_path = payload.get("card_path")
        if not isinstance(context, dict):
            raise CosmosStockAnalystError("COSMOS_RESPONSE_INVALID")
        if not include_chart:
            if raw_path is not None:
                raise CosmosStockAnalystError("COSMOS_RESPONSE_INVALID")
            return CosmosStockAnalystResult(context=context, chart_png=None)
        if not isinstance(raw_path, str):
            raise CosmosStockAnalystError("COSMOS_RESPONSE_INVALID")

        card_path = Path(raw_path).resolve()
        allowed_root = (self.runtime_root / "data/cards/axis-stock-analysis").resolve()
        if card_path != allowed_root and allowed_root not in card_path.parents:
            raise CosmosStockAnalystError("COSMOS_CARD_PATH_INVALID")
        try:
            chart = await asyncio.to_thread(card_path.read_bytes)
        except OSError as exc:
            raise CosmosStockAnalystError("COSMOS_CARD_READ_FAILED") from exc
        if (
            not chart.startswith(b"\x89PNG\r\n\x1a\n")
            or not chart
            or len(chart) > self.max_chart_bytes
        ):
            raise CosmosStockAnalystError("COSMOS_CARD_INVALID")
        return CosmosStockAnalystResult(context=context, chart_png=chart)


def merge_cosmos_analysis(
    payload: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Add current deterministic Cosmos evidence without replacing the manager thesis."""

    merged = dict(payload)
    ticker = str(context.get("ticker") or "").upper()
    trend_label = str(context.get("trend_label") or "方向未定")
    trend_score = context.get("trend_score")
    money_flow = context.get("money_flow") if isinstance(context.get("money_flow"), dict) else {}
    scenarios = context.get("scenarios") if isinstance(context.get("scenarios"), list) else []
    rotation = (
        context.get("sector_rotation")
        if isinstance(context.get("sector_rotation"), dict)
        else None
    )

    points = list(merged.get("supporting_points", []))
    if isinstance(trend_score, (int, float)):
        points.append(
            f"Cosmos Market Stock Analyst：{trend_label} {float(trend_score):.0f}/100。"
        )
    if money_flow:
        label = str(money_flow.get("label") or "不可用")
        score = money_flow.get("score")
        if isinstance(score, (int, float)):
            points.append(f"Cosmos OHLCV 资金流代理：{label} {float(score):.0f}/100。")
    if rotation:
        sector = str(context.get("sector_etf") or "板块")
        phase = str(rotation.get("rotation_phase") or rotation.get("label") or "观察")
        points.append(f"Cosmos 板块相对强度：{sector} · {phase}。")
    if scenarios:
        primary = max(
            (item for item in scenarios if isinstance(item, dict)),
            key=lambda item: float(item.get("model_weight_percent") or 0),
            default=None,
        )
        if primary:
            targets = primary.get("targets") if isinstance(primary.get("targets"), list) else []
            target_text = " / ".join(
                f"${float(value):,.2f}" for value in targets if isinstance(value, (int, float))
            )
            points.append(
                "Cosmos 当前主情景："
                f"{primary.get('label_zh') or primary.get('scenario_id')} · "
                f"模型权重 {float(primary.get('model_weight_percent') or 0):.0f}%"
                + (f" · 路径参考 {target_text}" if target_text else "")
                + "（权重不是胜率）。"
            )
    merged["supporting_points"] = _unique(points)

    levels = list(merged.get("key_levels", []))
    for source_name, level_type in (
        ("support_levels", "SUPPORT"),
        ("resistance_levels", "RESISTANCE"),
    ):
        raw_levels = context.get(source_name)
        if not isinstance(raw_levels, list):
            continue
        for item in raw_levels[:2]:
            if not isinstance(item, dict) or not isinstance(item.get("price"), (int, float)):
                continue
            levels.append(
                {
                    "symbol": ticker or None,
                    "level_type": level_type,
                    "price": float(item["price"]),
                    "note": "Cosmos Stock Analyst 日 K 结构聚类",
                }
            )
    merged["key_levels"] = _unique_levels(levels)

    market_conditions = list(merged.get("market_conditions", []))
    as_of = context.get("as_of")
    if ticker and as_of:
        market_conditions.append(f"Cosmos 数据截至 {as_of} · {ticker} 日 K。")
    merged["market_conditions"] = _unique(market_conditions)

    risks = list(merged.get("risks", []))
    risks.append("Cosmos 预测线是未校准的模型情景路径，不是胜率、承诺或交易指令。")
    risks.append("筹码峰与资金流为 OHLCV 代理，不代表逐笔主动买卖或暗池数据。")
    merged["risks"] = _unique(risks)

    warnings = list(merged.get("warnings", []))
    warnings.extend(
        ["COSMOS_SCENARIO_WEIGHT_NOT_PROBABILITY", "COSMOS_OHLCV_PROXY"]
    )
    merged["warnings"] = _unique(warnings)
    return merged


def _unique(values: list[Any]) -> list[Any]:
    output = []
    seen = set()
    for value in values:
        key = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            output.append(value)
            seen.add(key)
    return output


def _unique_levels(values: list[Any]) -> list[Any]:
    output = []
    seen: set[tuple[Any, ...]] = set()
    for value in values:
        if not isinstance(value, dict):
            continue
        price = value.get("price")
        key = (
            value.get("symbol"),
            value.get("level_type"),
            round(float(price), 4) if isinstance(price, (int, float)) else None,
            value.get("note"),
        )
        if key not in seen:
            output.append(value)
            seen.add(key)
    return output
