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
        await interaction.response.send_modal(AnalysisEditModal(self.controller, self.draft))

    async def rewrite(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.send_message(
            "请选择整理方式：",
            view=OneSelectView(RewriteSelect(self.controller, self.draft)),
            ephemeral=True,
        )

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
