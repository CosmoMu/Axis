from __future__ import annotations

import math
import uuid
from typing import TYPE_CHECKING, Any

import discord

from app.bot.ephemeral import (
    SUCCESS_DELETE_AFTER,
    send_temporary_ephemeral,
)
from app.services.analysis_pipeline import AnalysisDraftSnapshot

if TYPE_CHECKING:
    from app.bot.cogs.analysis_pipeline import AnalysisPipelineCog


ANALYSIS_TYPE_LABELS = {
    "MARKET": "市场",
    "TICKER": "个股",
    "SECTOR": "板块",
    "MACRO": "宏观",
}
STANCE_LABELS = {
    "BULLISH": "偏多",
    "BEARISH": "偏空",
    "NEUTRAL": "中性",
    "WATCH": "观察",
}
HORIZON_LABELS = {
    "INTRADAY": "日内",
    "SHORT_TERM": "短期",
    "SWING": "波段",
    "LONG_TERM": "长期",
    "UNSPECIFIED": "未指定",
}
STRUCTURE_LABELS = {
    "SUPPORT": "支撑",
    "RESISTANCE": "压力",
    "BREAKOUT": "突破",
    "TARGET": "目标",
    "INVALIDATION": "失效",
    "WATCH": "关注",
    "OTHER": "其他",
    "CURRENT": "当前位置",
    "START": "起点",
    "UP": "上行",
    "DOWN": "回落",
    "FLAT": "震荡",
    "KEY_ZONE": "关键区域",
    "PIVOT": "转折位",
    "STRUCTURE": "结构位置",
}

EDITABLE_LEVEL_ROLES = (
    "KEY_ZONE",
    "SUPPORT",
    "RESISTANCE",
    "PIVOT",
    "BREAKOUT",
    "TARGET",
    "INVALIDATION",
    "WATCH",
)


def _enum_value(value: str, labels: dict[str, str]) -> str:
    normalized = value.strip().upper()
    reverse = {label: key for key, label in labels.items()}
    return reverse.get(value.strip(), normalized)


def _price(value: str, *, required: bool = False) -> float | None:
    cleaned = value.strip().replace(",", "").removeprefix("$")
    if not cleaned:
        if required:
            raise ValueError("价格不能为空")
        return None
    parsed = float(cleaned)
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError("价格必须是大于 0 的数字")
    return parsed


def _sync_prediction_path(payload: dict[str, Any]) -> None:
    """Keep the deterministic chart route aligned with manager-approved levels."""

    current = payload.get("current_price")
    if not isinstance(current, (int, float)) or isinstance(current, bool) or current <= 0:
        current = next(
            (
                item.get("price")
                for item in payload.get("prediction_path", [])
                if isinstance(item, dict)
                and item.get("type") == "CURRENT"
                and isinstance(item.get("price"), (int, float))
            ),
            None,
        )
    if not isinstance(current, (int, float)) or isinstance(current, bool) or current <= 0:
        return

    levels = [item for item in payload.get("key_levels", []) if isinstance(item, dict)]
    bullish = str(payload.get("stance") or "WATCH") != "BEARISH"
    path: list[dict[str, Any]] = [
        {"type": "CURRENT", "price": float(current), "label": "当前", "sequence": 0}
    ]

    zones = [
        item
        for item in levels
        if item.get("role") in {"KEY_ZONE", "SUPPORT", "RESISTANCE", "PIVOT"}
        and isinstance(item.get("price"), (int, float))
        and (
            (bullish and float(item["price"]) <= float(current))
            or (not bullish and float(item["price"]) >= float(current))
        )
    ]
    if zones:
        zone = min(zones, key=lambda item: abs(float(item["price"]) - float(current)))
        zone_price = (
            float(zone["price"]) + float(zone.get("price_high") or zone["price"])
        ) / 2
        path.append(
            {
                "type": "STRUCTURE",
                "price": zone_price,
                "label": "关注区",
                "sequence": len(path),
            }
        )

    objectives = [
        item
        for item in levels
        if item.get("role") in {"BREAKOUT", "RESISTANCE", "SUPPORT", "TARGET"}
        and isinstance(item.get("price"), (int, float))
        and (
            (bullish and float(item["price"]) > float(current))
            or (not bullish and float(item["price"]) < float(current))
        )
    ]
    objectives.sort(key=lambda item: float(item["price"]), reverse=not bullish)
    for item in objectives[:4]:
        value = float(item["price"])
        if any(abs(value - float(point["price"])) / value < 0.0005 for point in path):
            continue
        role = str(item.get("role"))
        path.append(
            {
                "type": "BREAKOUT" if role == "BREAKOUT" else "TARGET",
                "price": value,
                "label": (
                    "关键突破"
                    if role == "BREAKOUT"
                    else str(item.get("description") or STRUCTURE_LABELS.get(role) or "目标")
                )[:80],
                "sequence": len(path),
            }
        )

    top = dict(payload.get("top_scenario") or {})
    invalidation = next(
        (
            item.get("price")
            for item in levels
            if item.get("role") == "INVALIDATION" and item.get("price") is not None
        ),
        None,
    )
    if invalidation is not None:
        top["invalidation"] = invalidation
    else:
        top.pop("invalidation", None)
    if len(path) < 2:
        payload["prediction_path"] = []
        top["direction_clear"] = False
        payload["top_scenario"] = top
        return
    payload["prediction_path"] = path
    top["direction_clear"] = True
    top.setdefault("model_weight_percent", 0)
    payload["top_scenario"] = top


class AnalysisLevelModal(discord.ui.Modal):
    def __init__(
        self,
        controller: AnalysisPipelineCog,
        draft: AnalysisDraftSnapshot,
        *,
        level_index: int | None = None,
        new_role: str | None = None,
    ) -> None:
        levels = draft.normalized.get("key_levels", [])
        existing = (
            levels[level_index]
            if level_index is not None
            and level_index < len(levels)
            and isinstance(levels[level_index], dict)
            else {}
        )
        role = str(existing.get("role") or new_role or "WATCH")
        super().__init__(
            title=f"{'新增' if level_index is None else '编辑'}点位 · {draft.draft_code}",
            timeout=300,
        )
        self.controller = controller
        self.draft = draft
        self.level_index = level_index
        self.role = discord.ui.TextInput(
            label="点位类型",
            default=STRUCTURE_LABELS.get(role, role),
            placeholder="关键区域 / 支撑 / 压力 / 突破 / 目标 / 失效",
            max_length=20,
        )
        self.value = discord.ui.TextInput(
            label="价格",
            default=str(existing.get("price") or ""),
            placeholder="例如 38.50",
            max_length=24,
        )
        self.upper = discord.ui.TextInput(
            label="区间上限（单一价位请留空）",
            default=str(existing.get("price_high") or ""),
            required=False,
            placeholder="例如 39.20",
            max_length=24,
        )
        self.description = discord.ui.TextInput(
            label="简短说明",
            default=str(existing.get("description") or existing.get("note") or ""),
            required=False,
            placeholder="例如：站稳后确认突破",
            max_length=180,
        )
        self.remove = discord.ui.TextInput(
            label="删除该点位（需要删除时输入：删除）",
            required=False,
            placeholder="平时留空",
            max_length=8,
        )
        for item in (self.role, self.value, self.upper, self.description, self.remove):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            payload = dict(self.draft.normalized)
            levels = [
                dict(item)
                for item in payload.get("key_levels", [])
                if isinstance(item, dict)
            ]
            deleting = self.remove.value.strip() == "删除"
            if deleting:
                if self.level_index is None or self.level_index >= len(levels):
                    raise ValueError("新点位尚未保存，无法删除")
                levels.pop(self.level_index)
                message = "点位已删除。"
            else:
                role = _enum_value(self.role.value, STRUCTURE_LABELS)
                if role not in EDITABLE_LEVEL_ROLES:
                    raise ValueError("点位类型无效")
                level = {
                    "symbol": (payload.get("symbols") or [None])[0],
                    "role": role,
                    "level_type": role,
                    "price": _price(self.value.value, required=True),
                    "price_high": _price(self.upper.value),
                    "strength": None,
                    "description": self.description.value.strip() or None,
                    "note": self.description.value.strip() or None,
                    "source": "MENTOR_INPUT",
                }
                if self.level_index is None:
                    levels.append(level)
                    message = "导师点位已新增。"
                else:
                    levels[self.level_index] = level
                    message = "导师点位已更新。"
            payload["key_levels"] = levels
            projection = payload.get("source_projection")
            if isinstance(projection, dict) and projection.get("present") is True:
                payload["source_projection"] = {
                    "present": False,
                    "attachment_index": None,
                    "evidence": "关键点位已由管理员确认并编辑。",
                    "path_points": [],
                }
            _sync_prediction_path(payload)
            updated = await self.controller.service.edit(
                self.draft.id,
                payload,
                actor_user_id=interaction.user.id,
                interaction_id=interaction.id,
            )
            await self.controller.refresh(updated)
            await send_temporary_ephemeral(
                interaction,
                message,
                delete_after=SUCCESS_DELETE_AFTER,
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)


class AnalysisLevelSelect(discord.ui.Select):
    def __init__(self, controller: AnalysisPipelineCog, draft: AnalysisDraftSnapshot) -> None:
        self.controller = controller
        self.draft = draft
        options: list[discord.SelectOption] = []
        for index, item in enumerate(draft.normalized.get("key_levels", [])[:17]):
            if not isinstance(item, dict) or item.get("price") is None:
                continue
            role = str(item.get("role") or item.get("level_type") or "WATCH")
            source = "导师" if item.get("source") == "MENTOR_INPUT" else "AXIS"
            options.append(
                discord.SelectOption(
                    label=(
                        f"编辑 · {STRUCTURE_LABELS.get(role, role)} · "
                        f"{float(item['price']):g} · {source}"
                    )[:100],
                    value=f"EDIT:{index}",
                )
            )
        for role in EDITABLE_LEVEL_ROLES:
            options.append(
                discord.SelectOption(
                    label=f"＋ 新增{STRUCTURE_LABELS[role]}",
                    value=f"NEW:{role}",
                )
            )
        super().__init__(
            placeholder="选择关键点位进行编辑或新增",
            options=options[:25],
            row=1,
            custom_id=f"axis:analysis:level:select:{draft.id.hex}:v{draft.version}",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        action, value = self.values[0].split(":", maxsplit=1)
        await interaction.response.send_modal(
            AnalysisLevelModal(
                self.controller,
                self.draft,
                level_index=int(value) if action == "EDIT" else None,
                new_role=value if action == "NEW" else None,
            )
        )


class AnalysisEditModal(discord.ui.Modal):
    def __init__(self, controller: AnalysisPipelineCog, draft: AnalysisDraftSnapshot) -> None:
        super().__init__(title=f"编辑 {draft.draft_code}", timeout=300)
        self.controller = controller
        self.draft = draft
        p = draft.normalized
        self.classification = discord.ui.TextInput(
            label="类型｜方向｜周期",
            default=(
                f"{ANALYSIS_TYPE_LABELS.get(str(p.get('analysis_type')), '个股')} | "
                f"{STANCE_LABELS.get(str(p.get('stance')), '观察')} | "
                f"{HORIZON_LABELS.get(str(p.get('time_horizon')), '未指定')}"
            ),
        )
        self.subject = discord.ui.TextInput(
            label="标的｜板块｜相关标的",
            default=(
                f"{','.join(p.get('symbols', []))} | {p.get('sector') or '-'} | "
                f"{','.join(p.get('related_symbols', []))}"
            ),
            required=False,
        )
        self.title_input = discord.ui.TextInput(
            label="标题", default=p.get("title") or "", required=False, max_length=160
        )
        self.summary = discord.ui.TextInput(
            label="摘要",
            default=p.get("summary") or "",
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=1200,
        )
        self.thesis = discord.ui.TextInput(
            label="核心逻辑",
            default=p.get("core_thesis") or "",
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=3000,
        )
        for item in (
            self.classification,
            self.subject,
            self.title_input,
            self.summary,
            self.thesis,
        ):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            payload = dict(self.draft.normalized)
            kind, stance, horizon = [x.strip() for x in self.classification.value.split("|")]
            symbols, sector, related = [x.strip() for x in self.subject.value.split("|")]
            payload.update(
                analysis_type=_enum_value(kind, ANALYSIS_TYPE_LABELS),
                stance=_enum_value(stance, STANCE_LABELS),
                time_horizon=_enum_value(horizon, HORIZON_LABELS),
                symbols=[x.strip().upper() for x in symbols.split(",") if x.strip()],
                sector=None if sector in {"", "-", "—"} else sector,
                related_symbols=[x.strip().upper() for x in related.split(",") if x.strip()],
                title=self.title_input.value.strip() or None,
                summary=self.summary.value.strip() or None,
                core_thesis=self.thesis.value.strip() or None,
            )
            updated = await self.controller.service.edit(
                self.draft.id,
                payload,
                actor_user_id=interaction.user.id,
                interaction_id=interaction.id,
            )
            await self.controller.refresh(updated)
            await send_temporary_ephemeral(
                interaction,
                "观点草稿已更新。",
                delete_after=SUCCESS_DELETE_AFTER,
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)


class AnalysisStructureEditModal(discord.ui.Modal):
    def __init__(self, controller: AnalysisPipelineCog, draft: AnalysisDraftSnapshot) -> None:
        super().__init__(title=f"结构与风险 {draft.draft_code}", timeout=300)
        self.controller = controller
        self.draft = draft
        payload = draft.normalized
        level_lines = []
        for item in payload.get("key_levels", []):
            if not isinstance(item, dict):
                continue
            level_lines.append(
                " | ".join(
                    str(value) if value is not None else ""
                    for value in (
                        STRUCTURE_LABELS.get(
                            str(item.get("role") or item.get("level_type") or "WATCH"),
                            "关注",
                        ),
                        item.get("price"),
                        item.get("price_high"),
                        item.get("strength"),
                        item.get("description") or item.get("note"),
                    )
                )
            )
        indicator_lines = []
        for item in payload.get("indicators", []):
            if isinstance(item, dict):
                indicator_lines.append(
                    " | ".join(
                        str(value) if value is not None else ""
                        for value in (
                            item.get("indicator_name"),
                            item.get("value"),
                            item.get("interpretation"),
                        )
                    )
                )
        top = payload.get("top_scenario") or {}
        path_lines = [
            f"权重 | {top.get('model_weight_percent') or ''} | "
            f"失效 | {top.get('invalidation') or ''}"
        ]
        for item in payload.get("prediction_path", []):
            if isinstance(item, dict):
                path_lines.append(
                    " | ".join(
                        str(value) if value is not None else ""
                        for value in (
                            STRUCTURE_LABELS.get(str(item.get("type")), "结构位置"),
                            item.get("price"),
                            item.get("label"),
                        )
                    )
                )
        self.levels = discord.ui.TextInput(
            label="角色｜价格｜上限｜强度｜说明",
            default="\n".join(level_lines)[:4000],
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=4000,
        )
        self.indicators = discord.ui.TextInput(
            label="指标｜数值｜解读",
            default="\n".join(indicator_lines)[:4000],
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=4000,
        )
        self.path = discord.ui.TextInput(
            label="权重、失效位与预测路径",
            default="\n".join(path_lines)[:4000],
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=4000,
        )
        self.invalidation = discord.ui.TextInput(
            label="失效条件",
            default=payload.get("invalidation") or "",
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=1500,
        )
        self.risks = discord.ui.TextInput(
            label="主要风险（每行一项）",
            default="\n".join(payload.get("risks", []))[:4000],
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=4000,
        )
        for item in (self.levels, self.indicators, self.path, self.invalidation, self.risks):
            self.add_item(item)

    @staticmethod
    def _number(value: str) -> float | None:
        try:
            return float(value.strip().removeprefix("$")) if value.strip() else None
        except ValueError:
            return None

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            payload = dict(self.draft.normalized)
            levels = []
            for line in self.levels.value.splitlines():
                parts = [item.strip() for item in line.split("|")]
                if not parts or not parts[0]:
                    continue
                parts.extend([""] * (5 - len(parts)))
                levels.append(
                    {
                        "symbol": (payload.get("symbols") or [None])[0],
                        "role": _enum_value(parts[0], STRUCTURE_LABELS),
                        "level_type": _enum_value(parts[0], STRUCTURE_LABELS),
                        "price": self._number(parts[1]),
                        "price_high": self._number(parts[2]),
                        "strength": self._number(parts[3]),
                        "description": parts[4] or None,
                        "note": parts[4] or None,
                        "source": "MENTOR_INPUT",
                    }
                )
            indicators = []
            for line in self.indicators.value.splitlines():
                parts = [item.strip() for item in line.split("|", maxsplit=2)]
                parts.extend([""] * (3 - len(parts)))
                if parts[0]:
                    numeric_value = self._number(parts[1])
                    indicators.append(
                        {
                            "indicator_name": parts[0],
                            "value": (
                                numeric_value if numeric_value is not None else parts[1] or None
                            ),
                            "interpretation": parts[2] or None,
                            "source": "MENTOR_INPUT",
                        }
                    )
            path_lines = [line for line in self.path.value.splitlines() if line.strip()]
            top = dict(payload.get("top_scenario") or {})
            path = []
            if path_lines:
                header = [item.strip() for item in path_lines[0].split("|")]
                if len(header) >= 4 and header[0].strip().upper() in {"WEIGHT", "权重"}:
                    weight = self._number(header[1])
                    invalidation = self._number(header[3])
                    if weight is not None:
                        top["model_weight_percent"] = weight
                    top["invalidation"] = invalidation
                    path_lines = path_lines[1:]
                for sequence, line in enumerate(path_lines):
                    parts = [item.strip() for item in line.split("|", maxsplit=2)]
                    parts.extend([""] * (3 - len(parts)))
                    price = self._number(parts[1])
                    if parts[0] and price is not None:
                        path.append(
                            {
                                "type": _enum_value(parts[0], STRUCTURE_LABELS),
                                "price": price,
                                "label": parts[2] or parts[0],
                                "sequence": sequence,
                            }
                        )
            if top:
                scenarios = list(payload.get("scenarios", []))
                second = (
                    float(scenarios[1].get("model_weight_percent") or 0)
                    if len(scenarios) > 1
                    else 0
                )
                weight = float(top.get("model_weight_percent") or 0)
                top["direction_clear"] = weight >= 50 and weight - second >= 10 and len(path) >= 2
            payload.update(
                key_levels=levels,
                indicators=indicators,
                top_scenario=top or None,
                prediction_path=path if top.get("direction_clear") else [],
                invalidation=self.invalidation.value.strip() or None,
                risks=[item.strip() for item in self.risks.value.splitlines() if item.strip()],
            )
            updated = await self.controller.service.edit(
                self.draft.id,
                payload,
                actor_user_id=interaction.user.id,
                interaction_id=interaction.id,
            )
            await self.controller.refresh(updated)
            await send_temporary_ephemeral(
                interaction,
                "最终结构已更新。",
                delete_after=SUCCESS_DELETE_AFTER,
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)


class AnalysisEditSelect(discord.ui.Select):
    def __init__(self, controller: AnalysisPipelineCog, draft: AnalysisDraftSnapshot) -> None:
        self.controller = controller
        self.draft = draft
        super().__init__(
            placeholder="选择编辑内容",
            options=(
                discord.SelectOption(label="标题、方向与核心逻辑", value="OVERVIEW"),
                discord.SelectOption(label="指标、路径与风险（高级）", value="STRUCTURE"),
            ),
            custom_id=f"axis:analysis:edit:select:{draft.id.hex}:v{draft.version}",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        modal = (
            AnalysisEditModal(self.controller, self.draft)
            if self.values[0] == "OVERVIEW"
            else AnalysisStructureEditModal(self.controller, self.draft)
        )
        await interaction.response.send_modal(modal)


class AnalysisMentorSelect(discord.ui.Select):
    def __init__(
        self,
        controller: AnalysisPipelineCog,
        draft: AnalysisDraftSnapshot,
        choices: list[tuple[uuid.UUID, str]],
    ) -> None:
        self.controller = controller
        self.draft = draft
        if choices:
            options = [
                discord.SelectOption(
                    label=name[:100],
                    value=str(mid),
                    default=name == draft.mentor_name,
                )
                for mid, name in choices
            ]
        else:
            options = [discord.SelectOption(label="没有可用导师", value="none-mentor")]
        super().__init__(
            placeholder=(
                f"导师 · {draft.mentor_name}" if draft.mentor_name else "选择导师"
            )[:150],
            min_values=1,
            max_values=1,
            options=options,
            disabled=not choices,
            row=0,
            custom_id=f"axis:analysis:mentor:select:{draft.id.hex}:v{draft.version}",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            updated = await self.controller.service.select_mentor(
                self.draft.id,
                uuid.UUID(self.values[0]),
                actor_user_id=interaction.user.id,
                interaction_id=interaction.id,
            )
            await self.controller.refresh(updated)
            await send_temporary_ephemeral(
                interaction,
                "导师已保存。",
                delete_after=SUCCESS_DELETE_AFTER,
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)


class OneSelectView(discord.ui.View):
    def __init__(self, item: discord.ui.Item[Any]) -> None:
        super().__init__(timeout=180)
        self.add_item(item)


class RewriteSelect(discord.ui.Select):
    OPTIONS = ("更简洁", "保留更多细节", "更偏交易视角", "更偏市场分析", "重新识别原文")

    def __init__(self, controller: AnalysisPipelineCog, draft: AnalysisDraftSnapshot) -> None:
        self.controller = controller
        self.draft = draft
        super().__init__(
            placeholder="选择重新整理方式",
            options=[discord.SelectOption(label=item, value=item) for item in self.OPTIONS],
            custom_id=f"axis:analysis:rewrite:select:{draft.id.hex}:v{draft.version}",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            updated = await self.controller.service.rewrite(
                self.draft.id,
                self.values[0],
                actor_user_id=interaction.user.id,
                interaction_id=interaction.id,
            )
            await self.controller.refresh(updated)
            await send_temporary_ephemeral(
                interaction,
                "文本已重新生成。",
                delete_after=SUCCESS_DELETE_AFTER,
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)


class AnalysisReviewView(discord.ui.View):
    def __init__(
        self,
        controller: AnalysisPipelineCog,
        draft: AnalysisDraftSnapshot,
        *,
        mentor_choices: list[tuple[uuid.UUID, str]],
    ) -> None:
        super().__init__(timeout=None)
        self.controller = controller
        self.draft = draft
        self.add_item(AnalysisMentorSelect(controller, draft, mentor_choices))
        self.add_item(AnalysisLevelSelect(controller, draft))
        definitions = (
            ("编辑文字", "edit", discord.ButtonStyle.primary, 2, self.edit),
            ("预览", "preview", discord.ButtonStyle.primary, 2, self.preview),
            ("重新生成文本", "rewrite", discord.ButtonStyle.secondary, 2, self.rewrite),
            ("重新生成图片", "chart", discord.ButtonStyle.secondary, 2, self.chart),
            ("仅归档", "archive", discord.ButtonStyle.secondary, 3, self.archive),
            ("归档并发布", "publish", discord.ButtonStyle.success, 3, self.publish),
            ("删除", "delete", discord.ButtonStyle.danger, 3, self.delete),
        )
        for label, action, style, row, callback in definitions:
            button = discord.ui.Button(
                label=label,
                style=style,
                row=row,
                custom_id=f"axis:analysis:{action}:{draft.id.hex}:v{draft.version}",
            )
            button.callback = callback
            self.add_item(button)

    async def edit(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.send_message(
            "请选择要编辑的最终分析内容：",
            view=OneSelectView(AnalysisEditSelect(self.controller, self.draft)),
            ephemeral=True,
            delete_after=180,
        )

    async def preview(self, interaction: discord.Interaction) -> None:
        await self.controller.preview_interaction(interaction, self.draft)

    async def rewrite(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.send_message(
            "请选择文本重新生成方式：",
            view=OneSelectView(RewriteSelect(self.controller, self.draft)),
            ephemeral=True,
            delete_after=180,
        )

    async def chart(self, interaction: discord.Interaction) -> None:
        await self.controller.retry_chart_interaction(interaction, self.draft)

    async def archive(self, interaction: discord.Interaction) -> None:
        await self.controller.archive_interaction(interaction, self.draft, publish=False)

    async def publish(self, interaction: discord.Interaction) -> None:
        await self.controller.archive_interaction(interaction, self.draft, publish=True)

    async def delete(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            updated = await self.controller.service.delete(
                self.draft.id, actor_user_id=interaction.user.id, interaction_id=interaction.id
            )
            await self.controller.refresh(updated)
            await send_temporary_ephemeral(
                interaction,
                "观点草稿已删除。",
                delete_after=SUCCESS_DELETE_AFTER,
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)


class AnalysisRetryView(discord.ui.View):
    def __init__(self, controller: AnalysisPipelineCog, draft: AnalysisDraftSnapshot) -> None:
        super().__init__(timeout=None)
        self.controller = controller
        self.draft = draft
        button = discord.ui.Button(
            label="重试发布",
            style=discord.ButtonStyle.success,
            custom_id=f"axis:analysis:retry:{draft.id.hex}:v{draft.version}",
        )
        button.callback = self.retry
        self.add_item(button)

    async def retry(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            result = await self.controller.service.retry_publication(self.draft.id)
            updated = await self.controller.publish_result(result)
            await self.controller.refresh(updated)
            await send_temporary_ephemeral(
                interaction,
                "观点已发布。",
                delete_after=SUCCESS_DELETE_AFTER,
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)
