from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import discord

from app.services.analysis_pipeline import AnalysisDraftSnapshot

if TYPE_CHECKING:
    from app.bot.cogs.analysis_pipeline import AnalysisPipelineCog


class AnalysisEditModal(discord.ui.Modal):
    def __init__(self, controller: AnalysisPipelineCog, draft: AnalysisDraftSnapshot) -> None:
        super().__init__(title=f"编辑 {draft.draft_code}", timeout=300)
        self.controller = controller
        self.draft = draft
        p = draft.normalized
        self.classification = discord.ui.TextInput(
            label="TYPE | STANCE | HORIZON",
            default=f"{p.get('analysis_type')} | {p.get('stance')} | {p.get('time_horizon')}",
        )
        self.subject = discord.ui.TextInput(
            label="Symbols | Sector | Related Symbols",
            default=(
                f"{','.join(p.get('symbols', []))} | {p.get('sector') or '-'} | "
                f"{','.join(p.get('related_symbols', []))}"
            ),
            required=False,
        )
        self.title_input = discord.ui.TextInput(
            label="Title", default=p.get("title") or "", required=False, max_length=160
        )
        self.summary = discord.ui.TextInput(
            label="Summary",
            default=p.get("summary") or "",
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=1200,
        )
        self.thesis = discord.ui.TextInput(
            label="Core Thesis",
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
            kind, stance, horizon = [
                x.strip().upper() for x in self.classification.value.split("|")
            ]
            symbols, sector, related = [x.strip() for x in self.subject.value.split("|")]
            payload.update(
                analysis_type=kind,
                stance=stance,
                time_horizon=horizon,
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
            await interaction.followup.send("观点草稿已更新。", ephemeral=True)
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
                        item.get("role") or item.get("level_type") or "WATCH",
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
            f"WEIGHT | {top.get('model_weight_percent') or ''} | "
            f"INVALIDATION | {top.get('invalidation') or ''}"
        ]
        for item in payload.get("prediction_path", []):
            if isinstance(item, dict):
                path_lines.append(
                    " | ".join(
                        str(value) if value is not None else ""
                        for value in (item.get("type"), item.get("price"), item.get("label"))
                    )
                )
        self.levels = discord.ui.TextInput(
            label="ROLE | PRICE | HIGH | STRENGTH | NOTE",
            default="\n".join(level_lines)[:4000],
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=4000,
        )
        self.indicators = discord.ui.TextInput(
            label="INDICATOR | VALUE | INTERPRETATION",
            default="\n".join(indicator_lines)[:4000],
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=4000,
        )
        self.path = discord.ui.TextInput(
            label="WEIGHT / INVALIDATION + PATH POINTS",
            default="\n".join(path_lines)[:4000],
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=4000,
        )
        self.invalidation = discord.ui.TextInput(
            label="Invalidation Text",
            default=payload.get("invalidation") or "",
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=1500,
        )
        self.risks = discord.ui.TextInput(
            label="Risk · one per line",
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
                        "role": parts[0].upper(),
                        "level_type": parts[0].upper(),
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
                if len(header) >= 4 and header[0].upper() == "WEIGHT":
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
                                "type": parts[0].upper(),
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
            await interaction.followup.send("最终结构已更新。", ephemeral=True)
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
                discord.SelectOption(label="点位、指标、路径与风险", value="STRUCTURE"),
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
        super().__init__(
            placeholder="选择 Mentor",
            options=[discord.SelectOption(label=name, value=str(mid)) for mid, name in choices],
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
            await interaction.followup.send("Mentor 已保存。", ephemeral=True)
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
            await interaction.followup.send("已生成新的 Draft Revision。", ephemeral=True)
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)


class AnalysisReviewView(discord.ui.View):
    def __init__(self, controller: AnalysisPipelineCog, draft: AnalysisDraftSnapshot) -> None:
        super().__init__(timeout=None)
        self.controller = controller
        self.draft = draft
        definitions = (
            ("选择 Mentor", "mentor", discord.ButtonStyle.secondary, self.mentor),
            ("编辑", "edit", discord.ButtonStyle.primary, self.edit),
            ("重新整理", "rewrite", discord.ButtonStyle.secondary, self.rewrite),
            ("重试图表", "chart", discord.ButtonStyle.secondary, self.chart),
            ("仅归档", "archive", discord.ButtonStyle.secondary, self.archive),
            ("归档并发布", "publish", discord.ButtonStyle.success, self.publish),
            ("删除草稿", "delete", discord.ButtonStyle.danger, self.delete),
        )
        for label, action, style, callback in definitions:
            button = discord.ui.Button(
                label=label,
                style=style,
                custom_id=f"axis:analysis:{action}:{draft.id.hex}:v{draft.version}",
            )
            button.callback = callback
            self.add_item(button)

    async def mentor(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        choices = await self.controller.service.mentor_choices(self.draft.guild_id)
        if not choices:
            await interaction.response.send_message("当前没有 Active Mentor。", ephemeral=True)
            return
        await interaction.response.send_message(
            "请选择 Mentor：",
            view=OneSelectView(AnalysisMentorSelect(self.controller, self.draft, choices)),
            ephemeral=True,
        )

    async def edit(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.send_message(
            "请选择要编辑的 Final Analysis 部分：",
            view=OneSelectView(AnalysisEditSelect(self.controller, self.draft)),
            ephemeral=True,
        )

    async def rewrite(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.send_message(
            "请选择整理方式：",
            view=OneSelectView(RewriteSelect(self.controller, self.draft)),
            ephemeral=True,
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
            await interaction.followup.send("观点草稿已删除。", ephemeral=True)
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
            await interaction.followup.send("观点已发布。", ephemeral=True)
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)
