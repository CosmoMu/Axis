from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

import discord

from app.bot.cards import build_active_orders_embed
from app.bot.ephemeral import (
    SUCCESS_DELETE_AFTER,
    send_temporary_ephemeral,
)
from app.domain.enums import TradeCategory
from app.domain.public_cards import PublicTradeCard
from app.services.card_review import (
    DraftEdit,
    ReviewChoice,
    ReviewDraft,
    ReviewValidationError,
    ShortTermDraftEdit,
    public_preview_payload,
)

if TYPE_CHECKING:
    from app.bot.cogs.card_review import CardReviewCog


def _display(value: object | None) -> str:
    return "-" if value is None else str(value)


def _decimal_display(value: Decimal | None) -> str:
    if value is None:
        return "-"
    rendered = f"{value:f}"
    return (rendered.rstrip("0").rstrip(".") if "." in rendered else rendered) or "0"


def _split(raw: str, count: int) -> list[str]:
    parts = [part.strip() for part in raw.replace("｜", "|").split("|")]
    if len(parts) != count:
        raise ReviewValidationError("FORM_FORMAT_INVALID")
    return parts


def _optional_text(raw: str) -> str | None:
    value = raw.strip()
    return None if value in {"", "-", "—", "NULL"} else value


def _optional_decimal(raw: str) -> Decimal | None:
    value = _optional_text(raw.replace("$", "").replace("%", ""))
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ReviewValidationError("NUMBER_INVALID") from exc


def _optional_date(raw: str) -> date | None:
    value = _optional_text(raw)
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ReviewValidationError("DATE_INVALID") from exc


def _optional_eighths(raw: str) -> int | None:
    value = _optional_text(raw.upper().replace(" ", ""))
    if value is None:
        return None
    aliases = {
        "1/8": 1,
        "1/4": 2,
        "3/8": 3,
        "1/2": 4,
        "5/8": 5,
        "3/4": 6,
        "7/8": 7,
        "FULL": 8,
        "满仓": 8,
    }
    if value in aliases:
        return aliases[value]
    if value.endswith("/8"):
        value = value[:-2]
    try:
        return int(value)
    except ValueError as exc:
        raise ReviewValidationError("POSITION_INVALID") from exc


class DraftEditModal(discord.ui.Modal):
    def __init__(self, controller: CardReviewCog, draft: ReviewDraft) -> None:
        super().__init__(
            title=f"编辑 {draft.draft_code}"[:45],
            timeout=300,
            custom_id=f"axis:review:modal:{draft.id.hex}:v{draft.version}",
        )
        self.controller = controller
        self.draft = draft
        self.operation = discord.ui.TextInput(
            label="意图 | 操作 | 阶段 | 分类",
            default=" | ".join(
                (
                    draft.intent,
                    draft.action,
                    _display(draft.action_stage),
                    _display(draft.selected_category),
                )
            ),
            placeholder="NEW_TRADE | ENTRY | NONE | SHORT_TERM",
            max_length=100,
        )
        self.contract = discord.ui.TextInput(
            label="Ticker | YYYY-MM-DD | Strike | CALL/PUT",
            default=" | ".join(
                (
                    _display(draft.ticker),
                    _display(draft.expiry),
                    _decimal_display(draft.strike),
                    _display(draft.option_side),
                )
            ),
            max_length=100,
        )
        self.prices = discord.ui.TextInput(
            label="入场低 | 入场高 | 操作价 | 平均成本",
            default=" | ".join(
                (
                    _decimal_display(draft.entry_low),
                    _decimal_display(draft.entry_high),
                    _decimal_display(draft.action_price),
                    _decimal_display(draft.avg_cost),
                )
            ),
            max_length=100,
        )
        self.risk = discord.ui.TextInput(
            label="SL | TP1 | TP2 | 当前收益%",
            default=" | ".join(
                (
                    _decimal_display(draft.sl),
                    _decimal_display(draft.tp1),
                    _decimal_display(draft.tp2),
                    _decimal_display(draft.current_pnl_pct),
                )
            ),
            max_length=100,
        )
        self.position = discord.ui.TextInput(
            label="本次仓位 | 操作后持仓（八分之一单位）",
            default=(
                f"{_display(draft.position_delta_eighths)} | "
                f"{_display(draft.position_after_eighths)}"
            ),
            placeholder="1 | 2（也支持 1/8 | 1/4）",
            max_length=50,
        )
        for item in (self.operation, self.contract, self.prices, self.risk, self.position):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        try:
            intent, action, stage, category = _split(self.operation.value, 4)
            ticker, expiry, strike, side = _split(self.contract.value, 4)
            entry_low, entry_high, action_price, avg_cost = _split(self.prices.value, 4)
            sl, tp1, tp2, pnl = _split(self.risk.value, 4)
            position_delta, position_after = _split(self.position.value, 2)
            values = DraftEdit(
                intent=intent.upper(),
                action=action.upper(),
                action_stage=(value.upper() if (value := _optional_text(stage)) else None),
                selected_category=(value.upper() if (value := _optional_text(category)) else None),
                ticker=(value.upper() if (value := _optional_text(ticker)) else None),
                expiry=_optional_date(expiry),
                strike=_optional_decimal(strike),
                option_side=(value.upper() if (value := _optional_text(side)) else None),
                entry_low=_optional_decimal(entry_low),
                entry_high=_optional_decimal(entry_high),
                action_price=_optional_decimal(action_price),
                avg_cost=_optional_decimal(avg_cost),
                sl=_optional_decimal(sl),
                tp1=_optional_decimal(tp1),
                tp2=_optional_decimal(tp2),
                current_pnl_pct=_optional_decimal(pnl),
                position_delta_eighths=_optional_eighths(position_delta),
                position_after_eighths=_optional_eighths(position_after),
                current_stock=self.draft.current_stock,
                starter=self.draft.starter,
                add_zone_low=self.draft.add_zone_low,
                add_zone_high=self.draft.add_zone_high,
                stock_sl=self.draft.stock_sl,
                stock_pt1=self.draft.stock_pt1,
                stock_pt2=self.draft.stock_pt2,
                stock_pt3=self.draft.stock_pt3,
                fib_0618=self.draft.fib_0618,
                public_thesis=self.draft.public_thesis,
            )
            await interaction.response.defer(ephemeral=True)
            updated = await self.controller.service.edit(
                self.draft.id,
                values=values,
                expected_version=self.draft.version,
                actor_user_id=interaction.user.id,
                interaction_id=interaction.id,
            )
            await self.controller.refresh(updated)
            await send_temporary_ephemeral(
                interaction,
                "草稿已更新。",
                delete_after=SUCCESS_DELETE_AFTER,
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)


class EntryPlanEditModal(discord.ui.Modal):
    def __init__(
        self,
        controller: CardReviewCog,
        draft: ReviewDraft,
        preview_card: PublicTradeCard | None = None,
    ) -> None:
        super().__init__(
            title=f"编辑完整卡片 · {draft.draft_code}"[:45],
            timeout=300,
            custom_id=f"axis:review:entry-plan:{draft.id.hex}:v{draft.version}",
        )
        self.controller = controller
        self.draft = draft
        plan = preview_card or public_preview_payload(draft)
        self.contract = discord.ui.TextInput(
            label="Ticker | YYYY-MM-DD | Strike | CALL/PUT",
            default=" | ".join(
                (
                    _display(draft.ticker),
                    _display(draft.expiry),
                    _decimal_display(draft.strike),
                    _display(draft.option_side),
                )
            ),
            max_length=100,
        )
        self.option = discord.ui.TextInput(
            label="期权入场低 | 入场高 | 持仓成本 | 仓位",
            default=" | ".join(
                (
                    _decimal_display(draft.entry_low),
                    _decimal_display(draft.entry_high),
                    _decimal_display(draft.avg_cost),
                    _display(draft.position_after_eighths),
                )
            ),
            placeholder="0.90 | 0.90 | 0.90 | 1/8",
            max_length=100,
        )
        self.structure = discord.ui.TextInput(
            label="当前股价 | Starter | Add低 | Add高",
            default=" | ".join(
                _decimal_display(value)
                for value in (
                    plan.current_stock,
                    plan.starter,
                    plan.add_zone_low,
                    plan.add_zone_high,
                )
            ),
            max_length=120,
        )
        self.targets = discord.ui.TextInput(
            label="正股SL | PT1 | PT2 | PT3 | Fib 0.618",
            default=" | ".join(
                _decimal_display(value)
                for value in (
                    plan.stock_sl,
                    plan.stock_pt1,
                    plan.stock_pt2,
                    plan.stock_pt3,
                    plan.fib_0618,
                )
            ),
            max_length=140,
        )
        self.thesis = discord.ui.TextInput(
            label="会员卡片交易逻辑（可留空）",
            default=plan.public_thesis or "",
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=600,
        )
        for item in (self.contract, self.option, self.structure, self.targets, self.thesis):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        try:
            ticker, expiry, strike, side = _split(self.contract.value, 4)
            entry_low, entry_high, avg_cost, position_after = _split(self.option.value, 4)
            current, starter, add_low, add_high = _split(self.structure.value, 4)
            stock_sl, pt1, pt2, pt3, fib = _split(self.targets.value, 5)
            after = _optional_eighths(position_after)
            values = DraftEdit(
                intent="NEW_TRADE",
                action="ENTRY",
                action_stage="NONE",
                selected_category=(
                    self.draft.selected_category
                    or self.draft.category_suggestion
                    or TradeCategory.SWING.value
                ),
                ticker=(value.upper() if (value := _optional_text(ticker)) else None),
                expiry=_optional_date(expiry),
                strike=_optional_decimal(strike),
                option_side=(value.upper() if (value := _optional_text(side)) else None),
                entry_low=_optional_decimal(entry_low),
                entry_high=_optional_decimal(entry_high),
                action_price=self.draft.action_price,
                avg_cost=_optional_decimal(avg_cost),
                sl=self.draft.sl,
                tp1=self.draft.tp1,
                tp2=self.draft.tp2,
                current_pnl_pct=self.draft.current_pnl_pct,
                position_delta_eighths=after,
                position_after_eighths=after,
                current_stock=_optional_decimal(current),
                starter=_optional_decimal(starter),
                add_zone_low=_optional_decimal(add_low),
                add_zone_high=_optional_decimal(add_high),
                stock_sl=_optional_decimal(stock_sl),
                stock_pt1=_optional_decimal(pt1),
                stock_pt2=_optional_decimal(pt2),
                stock_pt3=_optional_decimal(pt3),
                fib_0618=_optional_decimal(fib),
                public_thesis=_optional_text(self.thesis.value),
                replace_plan=True,
            )
            await interaction.response.defer(ephemeral=True)
            updated = await self.controller.service.edit(
                self.draft.id,
                values=values,
                expected_version=self.draft.version,
                actor_user_id=interaction.user.id,
                interaction_id=interaction.id,
            )
            await self.controller.refresh(updated)
            await send_temporary_ephemeral(
                interaction,
                "完整卡片已更新，可点击「重新生成图片」再次刷新图表。",
                delete_after=SUCCESS_DELETE_AFTER,
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)


class ShortTermEditModal(discord.ui.Modal):
    def __init__(self, controller: CardReviewCog, draft: ReviewDraft) -> None:
        super().__init__(
            title=f"Edit Short-Term · {draft.draft_code}"[:45],
            timeout=300,
            custom_id=f"axis:review:short-edit:{draft.id.hex}:v{draft.version}",
        )
        self.controller = controller
        self.draft = draft
        entry = draft.entry_low or draft.entry_high or draft.action_price
        self.ticker = discord.ui.TextInput(
            label="Ticker", default=_display(draft.ticker), max_length=12
        )
        self.expiry = discord.ui.TextInput(
            label="Expiry · YYYY-MM-DD", default=_display(draft.expiry), max_length=10
        )
        self.strike = discord.ui.TextInput(
            label="Strike", default=_decimal_display(draft.strike), max_length=24
        )
        self.option_side = discord.ui.TextInput(
            label="Call / Put", default=_display(draft.option_side), max_length=4
        )
        self.entry_price = discord.ui.TextInput(
            label="Entry Price", default=_decimal_display(entry), max_length=24
        )
        for item in (
            self.ticker,
            self.expiry,
            self.strike,
            self.option_side,
            self.entry_price,
        ):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        try:
            expiry = _optional_date(self.expiry.value)
            strike = _optional_decimal(self.strike.value)
            entry = _optional_decimal(self.entry_price.value)
            if expiry is None or strike is None or entry is None:
                raise ReviewValidationError("SHORT_TERM_FIELDS_REQUIRED")
            values = ShortTermDraftEdit(
                selected_category="SHORT_TERM",
                ticker=self.ticker.value.strip().upper(),
                expiry=expiry,
                strike=strike,
                option_side=self.option_side.value.strip().upper(),
                entry_price=entry,
            )
            await interaction.response.defer(ephemeral=True)
            updated = await self.controller.service.edit_short_term(
                self.draft.id,
                values=values,
                expected_version=self.draft.version,
                actor_user_id=interaction.user.id,
                interaction_id=interaction.id,
            )
            await self.controller.refresh(updated)
            await send_temporary_ephemeral(
                interaction,
                "Short-Term 草稿已更新。",
                delete_after=SUCCESS_DELETE_AFTER,
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)


class ReviewChoiceSelect(discord.ui.Select):
    def __init__(
        self,
        controller: CardReviewCog,
        draft: ReviewDraft,
        *,
        kind: str,
        choices: list[ReviewChoice],
    ) -> None:
        self.controller = controller
        self.draft = draft
        self.kind = kind
        current_id = draft.mentor_id if kind == "mentor" else draft.matched_trade_id
        current_label = draft.mentor_name if kind == "mentor" else draft.matched_trade_code
        label = "Select Mentor" if kind == "mentor" else "Link Order"
        if choices:
            options = [
                discord.SelectOption(
                    label=choice.label[:100],
                    value=choice.value,
                    description=choice.description[:100] if choice.description else None,
                    default=current_id is not None and choice.value == str(current_id),
                )
                for choice in choices
            ]
        else:
            empty_label = "No active Mentor" if kind == "mentor" else "No active order"
            options = [discord.SelectOption(label=empty_label, value=f"none-{kind}")]
        super().__init__(
            placeholder=(f"{label} · {current_label}" if current_label else label)[:150],
            min_values=1,
            max_values=1,
            options=options,
            disabled=not choices,
            row=1 if kind == "mentor" else 2,
            custom_id=f"axis:review:{kind}:select:{draft.id.hex}:v{draft.version}",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            selected_id = uuid.UUID(self.values[0])
            common = {
                "expected_version": self.draft.version,
                "actor_user_id": interaction.user.id,
                "interaction_id": interaction.id,
            }
            if self.kind == "mentor":
                updated = await self.controller.service.select_mentor(
                    self.draft.id, mentor_id=selected_id, **common
                )
            else:
                updated = await self.controller.service.select_trade(
                    self.draft.id, trade_id=selected_id, **common
                )
            await self.controller.refresh(updated)
            await send_temporary_ephemeral(
                interaction,
                "选择已保存。",
                delete_after=SUCCESS_DELETE_AFTER,
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)


class ConfirmDeleteView(discord.ui.View):
    def __init__(self, controller: CardReviewCog, draft: ReviewDraft) -> None:
        super().__init__(timeout=120)
        self.controller = controller
        self.draft = draft

    @discord.ui.button(label="确认删除草稿", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            updated = await self.controller.service.delete(
                self.draft.id,
                expected_version=self.draft.version,
                actor_user_id=interaction.user.id,
                interaction_id=interaction.id,
            )
            await self.controller.refresh(updated)
            await send_temporary_ephemeral(
                interaction,
                "草稿已标记为删除。",
                delete_after=SUCCESS_DELETE_AFTER,
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)


class CategorySelect(discord.ui.Select):
    def __init__(self, controller: CardReviewCog, draft: ReviewDraft) -> None:
        self.controller = controller
        self.draft = draft
        current = draft.selected_category or draft.category_suggestion
        options = (
            ("短线 · Short-term", "SHORT_TERM", "分钟到数日"),
            ("波段 · Swing", "SWING", "数日到数周"),
            ("长期 · LEAPS", "LEAPS", "长期或 LEAPS"),
        )
        super().__init__(
            placeholder=f"CATEGORY · {current or 'SELECT'}",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label=label,
                    value=value,
                    description=description,
                    default=value == current,
                )
                for label, value, description in options
            ],
            row=0,
            custom_id=f"axis:review:category:select:{draft.id.hex}:v{draft.version}",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            updated = await self.controller.service.select_category(
                self.draft.id,
                category=self.values[0],
                expected_version=self.draft.version,
                actor_user_id=interaction.user.id,
                interaction_id=interaction.id,
            )
            await self.controller.refresh(updated)
            await send_temporary_ephemeral(
                interaction,
                "Category 已更新。",
                delete_after=SUCCESS_DELETE_AFTER,
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)


class ReviewDraftView(discord.ui.View):
    def __init__(
        self,
        controller: CardReviewCog,
        draft: ReviewDraft,
        *,
        mentor_choices: list[ReviewChoice],
        trade_choices: list[ReviewChoice],
        preview_card: PublicTradeCard | None = None,
    ) -> None:
        super().__init__(timeout=None)
        self.controller = controller
        self.draft = draft
        self.preview_card = preview_card
        self.add_item(CategorySelect(controller, draft))
        short_term = (draft.selected_category or draft.category_suggestion) == "SHORT_TERM"
        if short_term:
            buttons = (
                ("EDIT", discord.ButtonStyle.primary, "edit", 1, self.edit),
                (
                    f"LOTTO · {'YES' if draft.is_lotto else 'NO'}",
                    (
                        discord.ButtonStyle.success
                        if draft.is_lotto
                        else discord.ButtonStyle.secondary
                    ),
                    "lotto",
                    1,
                    self.toggle_lotto,
                ),
                ("PUBLISH", discord.ButtonStyle.success, "approve", 1, self.approve),
                ("DELETE", discord.ButtonStyle.danger, "delete", 1, self.delete),
            )
            for label, style, action, row, callback in buttons:
                button = discord.ui.Button(
                    label=label,
                    style=style,
                    row=row,
                    custom_id=f"axis:review:{action}:{draft.id.hex}:v{draft.version}",
                )
                button.callback = callback
                self.add_item(button)
            return
        self.add_item(ReviewChoiceSelect(controller, draft, kind="mentor", choices=mentor_choices))
        self.add_item(ReviewChoiceSelect(controller, draft, kind="trade", choices=trade_choices))
        buttons = (
            ("完整编辑", discord.ButtonStyle.primary, "edit", 3, self.edit),
            (
                "重新生成图片",
                discord.ButtonStyle.secondary,
                "regenerate-image",
                3,
                self.regenerate_image,
            ),
            ("确认发布", discord.ButtonStyle.success, "approve", 4, self.approve),
            (
                f"LOTTO · {'YES' if draft.is_lotto else 'NO'}",
                (
                    discord.ButtonStyle.success
                    if draft.is_lotto
                    else discord.ButtonStyle.secondary
                ),
                "lotto",
                4,
                self.toggle_lotto,
            ),
            ("删除", discord.ButtonStyle.danger, "delete", 4, self.delete),
        )
        for label, style, action, row, callback in buttons:
            button = discord.ui.Button(
                label=label,
                style=style,
                row=row,
                custom_id=f"axis:review:{action}:{draft.id.hex}:v{draft.version}",
            )
            button.callback = callback
            self.add_item(button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.controller.authorize(interaction)

    async def edit(self, interaction: discord.Interaction) -> None:
        if (self.draft.selected_category or self.draft.category_suggestion) == "SHORT_TERM":
            await interaction.response.send_modal(ShortTermEditModal(self.controller, self.draft))
        elif self.draft.intent == "NEW_TRADE" and self.draft.action == "ENTRY":
            await interaction.response.send_modal(
                EntryPlanEditModal(self.controller, self.draft, self.preview_card)
            )
        else:
            await interaction.response.send_modal(DraftEditModal(self.controller, self.draft))

    async def regenerate_image(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            generated = await self.controller.regenerate_review_image(self.draft.id)
            if not generated:
                raise ReviewValidationError("TRADE_PLAN_IMAGE_UNAVAILABLE")
            await send_temporary_ephemeral(
                interaction,
                "图片已根据当前卡片内容重新生成。",
                delete_after=SUCCESS_DELETE_AFTER,
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)

    async def toggle_lotto(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            updated = await self.controller.service.toggle_lotto(
                self.draft.id,
                expected_version=self.draft.version,
                actor_user_id=interaction.user.id,
                interaction_id=interaction.id,
            )
            await self.controller.refresh(updated)
            await send_temporary_ephemeral(
                interaction,
                f"LOTTO 已设为 {'YES' if updated.is_lotto else 'NO'}。",
                delete_after=SUCCESS_DELETE_AFTER,
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)

    async def approve(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            updated = await self.controller.service.approve(
                self.draft.id,
                expected_version=self.draft.version,
                actor_user_id=interaction.user.id,
                interaction_id=interaction.id,
            )
            updated = await self.controller.publish_draft(
                updated,
                actor_user_id=interaction.user.id,
                interaction_id=interaction.id,
            )
            await self.controller.refresh(updated)
            await send_temporary_ephemeral(
                interaction,
                (
                    "会员卡片已发布。"
                    if updated.status == "PUBLISHED"
                    else "已确认，会员卡片正在发布。"
                ),
                delete_after=SUCCESS_DELETE_AFTER,
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)

    async def delete(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "删除后该草稿不会进入发布队列。是否继续？",
            view=ConfirmDeleteView(self.controller, self.draft),
            ephemeral=True,
            delete_after=120,
        )


class PublicationRetryView(discord.ui.View):
    def __init__(self, controller: CardReviewCog, draft: ReviewDraft) -> None:
        super().__init__(timeout=None)
        self.controller = controller
        self.draft = draft
        button = discord.ui.Button(
            label="重新发布",
            style=discord.ButtonStyle.success,
            custom_id=f"axis:review:retry:{draft.id.hex}:v{draft.version}",
        )
        button.callback = self.retry
        self.add_item(button)

    async def retry(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            current = await self.controller.service.get(self.draft.id)
            updated = await self.controller.publish_draft(
                current,
                actor_user_id=interaction.user.id,
                interaction_id=interaction.id,
            )
            await self.controller.refresh(updated)
            await send_temporary_ephemeral(
                interaction,
                ("会员卡片已发布。" if updated.status == "PUBLISHED" else "重新发布已进入队列。"),
                delete_after=SUCCESS_DELETE_AFTER,
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)


class ActiveOrdersView(discord.ui.View):
    def __init__(self, controller: CardReviewCog, category: str) -> None:
        if category not in {TradeCategory.SWING.value, TradeCategory.LEAPS.value}:
            raise ValueError("ACTIVE_POSITION_VIEW_UNAVAILABLE")
        super().__init__(timeout=None)
        self.controller = controller
        self.category = category
        custom_id = {
            TradeCategory.SWING.value: "axis:active:swing:v1",
            TradeCategory.LEAPS.value: "axis:active:leaps:v1",
        }[category]
        button = discord.ui.Button(
            label="查看当前持仓订单",
            style=discord.ButtonStyle.secondary,
            custom_id=custom_id,
        )
        button.callback = self.show_orders
        self.add_item(button)

    async def show_orders(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize_member(interaction):
            return
        orders = await self.controller.publication_service.current_orders(
            self.controller.guild_id, self.category
        )
        await interaction.response.send_message(
            embed=build_active_orders_embed(self.category, orders),
            ephemeral=True,
        )
