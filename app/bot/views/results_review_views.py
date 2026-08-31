from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

import discord

from app.services.daily_results_review import EXCLUSION_REASONS, ResultsItemView

if TYPE_CHECKING:
    from app.bot.cogs.daily_results_review import DailyResultsReviewCog


class ResultsReviewView(discord.ui.View):
    def __init__(
        self,
        controller: DailyResultsReviewCog,
        review_id: uuid.UUID,
        *,
        locked: bool = False,
    ) -> None:
        super().__init__(timeout=None)
        self.controller = controller
        self.review_id = review_id
        definitions = (
            ("MANAGE TRADES", "manage", discord.ButtonStyle.secondary, self.manage, False),
            ("PREVIEW", "preview", discord.ButtonStyle.primary, self.preview, False),
            ("PUBLISH NOW", "publish", discord.ButtonStyle.success, self.publish, locked),
        )
        for label, action, style, callback, disabled in definitions:
            button = discord.ui.Button(
                label=label,
                style=style,
                custom_id=f"axis:results:{action}:{review_id}:v1",
                disabled=disabled,
            )
            button.callback = callback
            self.add_item(button)

    async def manage(self, interaction: discord.Interaction) -> None:
        await self.controller.open_manage(interaction, self.review_id)

    async def preview(self, interaction: discord.Interaction) -> None:
        await self.controller.show_preview(interaction, self.review_id)

    async def publish(self, interaction: discord.Interaction) -> None:
        await self.controller.publish_now(interaction, self.review_id)


class TradeSelect(discord.ui.Select):
    def __init__(
        self,
        controller: DailyResultsReviewCog,
        review_id: uuid.UUID,
        items: tuple[ResultsItemView, ...],
    ) -> None:
        self.controller = controller
        self.review_id = review_id
        self.item_map = {str(item.id): item for item in items[:25]}
        result_labels = {
            item.id: (
                str(item.display_result_pct)
                if item.display_result_pct is not None
                else "N/A"
            )
            for item in items[:25]
        }
        options = [
            discord.SelectOption(
                label=f"{item.public_trade_id} · {item.contract}"[:100],
                value=str(item.id),
                description=(
                    ("INCLUDED" if item.included else "EXCLUDED")
                    + f" · {result_labels[item.id]}%"
                )[:100],
                emoji="✅" if item.included else "⛔",
            )
            for item in items[:25]
        ]
        super().__init__(
            placeholder="选择一笔 Eligible Trade",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        item = self.item_map[self.values[0]]
        await interaction.response.send_message(
            f"{item.display_text}\n\n当前：{'INCLUDED' if item.included else 'EXCLUDED'}",
            view=ItemActionView(self.controller, self.review_id, item),
            ephemeral=True,
        )


class TradeSelectView(discord.ui.View):
    def __init__(
        self,
        controller: DailyResultsReviewCog,
        review_id: uuid.UUID,
        items: tuple[ResultsItemView, ...],
    ) -> None:
        super().__init__(timeout=300)
        self.add_item(TradeSelect(controller, review_id, items))


class ItemActionView(discord.ui.View):
    def __init__(
        self,
        controller: DailyResultsReviewCog,
        review_id: uuid.UUID,
        item: ResultsItemView,
    ) -> None:
        super().__init__(timeout=300)
        self.controller = controller
        self.review_id = review_id
        self.item = item
        definitions = (
            (
                "INCLUDE AGAIN",
                discord.ButtonStyle.success,
                self.include,
                item.included,
            ),
            (
                "EXCLUDE FROM DAILY RESULTS",
                discord.ButtonStyle.danger,
                self.exclude,
                not item.included,
            ),
            ("EDIT DISPLAY", discord.ButtonStyle.secondary, self.edit, False),
            ("CORRECT RESULT", discord.ButtonStyle.secondary, self.correct, False),
        )
        for label, style, callback, disabled in definitions:
            button = discord.ui.Button(label=label, style=style, disabled=disabled)
            button.callback = callback
            self.add_item(button)

    async def include(self, interaction: discord.Interaction) -> None:
        await self.controller.include_item(interaction, self.item.id)

    async def exclude(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "请选择 Exclusion Reason：",
            view=ExclusionReasonView(self.controller, self.item.id),
            ephemeral=True,
        )

    async def edit(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(ItemDisplayModal(self.controller, self.item))

    async def correct(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(CorrectResultModal(self.controller, self.item))


class ExclusionReasonSelect(discord.ui.Select):
    def __init__(self, controller: DailyResultsReviewCog, item_id: uuid.UUID) -> None:
        self.controller = controller
        self.item_id = item_id
        super().__init__(
            placeholder="Exclusion Reason",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label=reason, value=reason) for reason in EXCLUSION_REASONS
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.controller.exclude_item(interaction, self.item_id, self.values[0])


class ExclusionReasonView(discord.ui.View):
    def __init__(self, controller: DailyResultsReviewCog, item_id: uuid.UUID) -> None:
        super().__init__(timeout=300)
        self.add_item(ExclusionReasonSelect(controller, item_id))


class ItemDisplayModal(discord.ui.Modal):
    def __init__(self, controller: DailyResultsReviewCog, item: ResultsItemView) -> None:
        super().__init__(title=f"Edit Display · {item.public_trade_id}", timeout=300)
        self.controller = controller
        self.item = item
        self.display_text = discord.ui.TextInput(
            label="Public Display Text",
            style=discord.TextStyle.paragraph,
            default=item.display_text[:1000],
            max_length=1000,
            required=False,
        )
        self.add_item(self.display_text)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.controller.edit_item_display(
            interaction,
            self.item.id,
            self.display_text.value,
        )


class CorrectResultModal(discord.ui.Modal):
    def __init__(self, controller: DailyResultsReviewCog, item: ResultsItemView) -> None:
        super().__init__(title=f"Correct Result · {item.public_trade_id}", timeout=300)
        self.controller = controller
        self.item = item
        self.value = discord.ui.TextInput(
            label="Corrected Return %",
            placeholder="例如 42 或 -22.5",
            default=(str(item.display_result_pct) if item.display_result_pct is not None else ""),
            max_length=24,
        )
        self.reason = discord.ui.TextInput(
            label="Reason",
            style=discord.TextStyle.paragraph,
            placeholder="Market Data Error / Wrong Quote / Manual Correction",
            max_length=1000,
        )
        self.add_item(self.value)
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            value = Decimal(self.value.value.strip().rstrip("%"))
        except InvalidOperation:
            await interaction.response.send_message("收益率格式无效。", ephemeral=True)
            return
        await self.controller.correct_result(
            interaction,
            self.item.id,
            value,
            self.reason.value,
        )


class EditCardModal(discord.ui.Modal):
    def __init__(
        self,
        controller: DailyResultsReviewCog,
        review_id: uuid.UUID,
    ) -> None:
        super().__init__(title="Edit Daily Results Card", timeout=300)
        self.controller = controller
        self.review_id = review_id
        self.title_input = discord.ui.TextInput(
            label="Title",
            placeholder="AXIS DAILY RESULTS",
            required=False,
            max_length=200,
        )
        self.section_order = discord.ui.TextInput(
            label="Section Order",
            placeholder="SHORT_TERM, SWING, LEAPS",
            default="SHORT_TERM, SWING, LEAPS",
            max_length=100,
        )
        self.footer = discord.ui.TextInput(
            label="Footer",
            style=discord.TextStyle.paragraph,
            placeholder="Past performance does not guarantee future results.",
            required=False,
            max_length=1000,
        )
        self.add_item(self.title_input)
        self.add_item(self.section_order)
        self.add_item(self.footer)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.controller.edit_card(
            interaction,
            self.review_id,
            title=self.title_input.value,
            section_order=self.section_order.value,
            footer=self.footer.value,
        )
