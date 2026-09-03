from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

import discord

from app.bot.cards import build_active_orders_embed, build_swing_active_embed
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
    missing_field_labels,
    public_preview_payload,
    publication_missing_fields,
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


def _edit_values(draft: ReviewDraft, **changes: object) -> DraftEdit:
    values: dict[str, object] = {
        "intent": draft.intent,
        "action": draft.action,
        "action_stage": draft.action_stage,
        "selected_category": draft.selected_category,
        "ticker": draft.ticker,
        "expiry": draft.expiry,
        "strike": draft.strike,
        "option_side": draft.option_side,
        "entry_low": draft.entry_low,
        "entry_high": draft.entry_high,
        "action_price": draft.action_price,
        "avg_cost": draft.avg_cost,
        "sl": draft.sl,
        "tp1": draft.tp1,
        "tp2": draft.tp2,
        "current_pnl_pct": draft.current_pnl_pct,
        "position_delta_eighths": draft.position_delta_eighths,
        "position_after_eighths": draft.position_after_eighths,
        "current_stock": draft.current_stock,
        "starter": draft.starter,
        "add_zone_low": draft.add_zone_low,
        "add_zone_high": draft.add_zone_high,
        "stock_sl": draft.stock_sl,
        "stock_pt1": draft.stock_pt1,
        "stock_pt2": draft.stock_pt2,
        "stock_pt3": draft.stock_pt3,
        "fib_0618": draft.fib_0618,
        "public_thesis": draft.public_thesis,
        "replace_plan": False,
    }
    values.update(changes)
    return DraftEdit(**values)  # type: ignore[arg-type]


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


def _text_field(
    *,
    text: str,
    default: str,
    required: bool = False,
    description: str | None = None,
    placeholder: str | None = None,
    paragraph: bool = False,
    max_length: int = 100,
) -> tuple[discord.ui.TextInput, discord.ui.Label]:
    component = discord.ui.TextInput(
        default=default,
        required=required,
        placeholder=placeholder,
        style=discord.TextStyle.paragraph if paragraph else discord.TextStyle.short,
        max_length=max_length,
    )
    return component, discord.ui.Label(
        text=text,
        description=description,
        component=component,
    )


def _position_options(current: int | None) -> list[discord.SelectOption]:
    labels = (
        "0 · 清仓",
        "1 · 1/8 仓位",
        "2 · 1/4 仓位",
        "3 · 3/8 仓位",
        "4 · 1/2 仓位",
        "5 · 5/8 仓位",
        "6 · 3/4 仓位",
        "7 · 7/8 仓位",
        "8 · 满仓",
    )
    return [
        discord.SelectOption(label=label, value=str(value), default=value == current)
        for value, label in enumerate(labels)
    ]


class ContractEditModal(discord.ui.Modal):
    def __init__(self, controller: CardReviewCog, draft: ReviewDraft) -> None:
        super().__init__(
            title=f"编辑合约 · {draft.draft_code}"[:45],
            timeout=300,
            custom_id=f"axis:review:contract:{draft.id.hex}:v{draft.version}",
        )
        self.controller = controller
        self.draft = draft
        self.ticker, ticker_label = _text_field(
            text="Ticker",
            default=_display(draft.ticker),
            required=True,
            description="只填写股票代码，例如 HIMS",
            max_length=12,
        )
        self.expiry, expiry_label = _text_field(
            text="Expiry",
            default=_display(draft.expiry),
            required=True,
            description="只填写一个日期",
            placeholder="YYYY-MM-DD",
            max_length=10,
        )
        self.strike, strike_label = _text_field(
            text="Strike",
            default=_decimal_display(draft.strike),
            required=True,
            description="只填写行权价，例如 35",
            max_length=24,
        )
        self.option_side = discord.ui.Select(
            placeholder="选择 CALL 或 PUT",
            min_values=1,
            max_values=1,
            required=True,
            options=[
                discord.SelectOption(
                    label="CALL",
                    value="CALL",
                    default=draft.option_side == "CALL",
                ),
                discord.SelectOption(
                    label="PUT",
                    value="PUT",
                    default=draft.option_side == "PUT",
                ),
            ],
        )
        for item in (
            ticker_label,
            expiry_label,
            strike_label,
            discord.ui.Label(text="Call / Put", component=self.option_side),
        ):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        try:
            side = str(self.option_side.values[0]).upper()
            await interaction.response.defer(ephemeral=True)
            updated = await self.controller.service.edit(
                self.draft.id,
                values=_edit_values(
                    self.draft,
                    ticker=(
                        value.upper() if (value := _optional_text(self.ticker.value)) else None
                    ),
                    expiry=_optional_date(self.expiry.value),
                    strike=_optional_decimal(self.strike.value),
                    option_side=side,
                ),
                expected_version=self.draft.version,
                actor_user_id=interaction.user.id,
                interaction_id=interaction.id,
            )
            await self.controller.refresh(updated)
            await send_temporary_ephemeral(
                interaction,
                "合约已保存；发布时会再次验证 Option Chain。",
                delete_after=SUCCESS_DELETE_AFTER,
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)


class TradeValuesEditModal(discord.ui.Modal):
    def __init__(self, controller: CardReviewCog, draft: ReviewDraft) -> None:
        super().__init__(
            title=f"编辑价格与仓位 · {draft.draft_code}"[:45],
            timeout=300,
            custom_id=f"axis:review:values:{draft.id.hex}:v{draft.version}",
        )
        self.controller = controller
        self.draft = draft
        self.is_entry = draft.intent == "NEW_TRADE" and draft.action == "ENTRY"
        action_requires_price = draft.action in {
            "ADD",
            "TP1",
            "TP2",
            "PARTIAL_SL",
            "SL",
            "CLOSE",
            "ROLL",
        }
        if self.is_entry:
            primary_default = _decimal_display(draft.entry_low or draft.avg_cost)
            secondary_default = (
                _decimal_display(draft.entry_high)
                if draft.entry_high is not None and draft.entry_high != draft.entry_low
                else ""
            )
            self.primary, primary_label = _text_field(
                text="入场价",
                default=primary_default,
                required=True,
                description="必填；只有一个价格时填这里",
                max_length=24,
            )
            self.secondary, secondary_label = _text_field(
                text="入场价上限",
                default=secondary_default,
                description="可选；不是区间时留空",
                max_length=24,
            )
            self.average, average_label = _text_field(
                text="当前平均成本",
                default=_decimal_display(draft.avg_cost),
                description="可选；留空时系统使用入场价",
                max_length=24,
            )
            self.risk, risk_label = _text_field(
                text="期权 SL",
                default=_decimal_display(draft.sl),
                description="可选",
                max_length=24,
            )
        else:
            self.primary, primary_label = _text_field(
                text="本次操作价格",
                default=_decimal_display(draft.action_price),
                required=action_requires_price,
                description="加仓、止盈或平仓时必须填写",
                max_length=24,
            )
            self.secondary, secondary_label = _text_field(
                text="操作后平均成本",
                default=_decimal_display(draft.avg_cost),
                description="可选；例如加仓后均价",
                max_length=24,
            )
            self.average, average_label = _text_field(
                text="新 SL",
                default=_decimal_display(draft.sl),
                description="可选",
                max_length=24,
            )
            self.risk, risk_label = _text_field(
                text="下一个目标",
                default=_decimal_display(draft.tp1),
                description="可选",
                max_length=24,
            )
        self.position = discord.ui.Select(
            placeholder="选择操作后的总持仓",
            min_values=1,
            max_values=1,
            required=True,
            options=_position_options(draft.position_after_eighths),
        )
        for item in (
            primary_label,
            secondary_label,
            average_label,
            risk_label,
            discord.ui.Label(
                text="操作后总持仓",
                description="选择完成本次操作后的仓位，不是本次增减量",
                component=self.position,
            ),
        ):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        try:
            position_after = int(str(self.position.values[0]))
            if self.is_entry:
                entry_low = _optional_decimal(self.primary.value)
                if entry_low is None:
                    raise ReviewValidationError("ENTRY_PRICE_REQUIRED")
                values = _edit_values(
                    self.draft,
                    entry_low=entry_low,
                    entry_high=_optional_decimal(self.secondary.value) or entry_low,
                    action_price=None,
                    avg_cost=_optional_decimal(self.average.value),
                    sl=_optional_decimal(self.risk.value),
                    position_delta_eighths=position_after,
                    position_after_eighths=position_after,
                )
            else:
                values = _edit_values(
                    self.draft,
                    action_price=_optional_decimal(self.primary.value),
                    avg_cost=_optional_decimal(self.secondary.value),
                    sl=_optional_decimal(self.average.value),
                    tp1=_optional_decimal(self.risk.value),
                    position_delta_eighths=None,
                    position_after_eighths=position_after,
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
                "价格和操作后总持仓已保存。",
                delete_after=SUCCESS_DELETE_AFTER,
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)


class StockStructureEditModal(discord.ui.Modal):
    def __init__(self, controller: CardReviewCog, draft: ReviewDraft) -> None:
        super().__init__(
            title=f"编辑正股结构 · {draft.draft_code}"[:45],
            timeout=300,
            custom_id=f"axis:review:structure:{draft.id.hex}:v{draft.version}",
        )
        self.controller = controller
        self.draft = draft
        fields = (
            ("当前股价", "current", draft.current_stock),
            ("Starter", "starter", draft.starter),
            ("Add Zone 下限", "add_low", draft.add_zone_low),
            ("Add Zone 上限", "add_high", draft.add_zone_high),
            ("正股 SL", "stock_sl", draft.stock_sl),
        )
        for label_text, attribute, value in fields:
            component, label = _text_field(
                text=label_text,
                default=_decimal_display(value),
                description="可选；一个框只填写一个价格",
                max_length=24,
            )
            setattr(self, attribute, component)
            self.add_item(label)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        try:
            await interaction.response.defer(ephemeral=True)
            updated = await self.controller.service.edit(
                self.draft.id,
                values=_edit_values(
                    self.draft,
                    current_stock=_optional_decimal(self.current.value),
                    starter=_optional_decimal(self.starter.value),
                    add_zone_low=_optional_decimal(self.add_low.value),
                    add_zone_high=_optional_decimal(self.add_high.value),
                    stock_sl=_optional_decimal(self.stock_sl.value),
                    replace_plan=True,
                ),
                expected_version=self.draft.version,
                actor_user_id=interaction.user.id,
                interaction_id=interaction.id,
            )
            await self.controller.refresh(updated)
            await send_temporary_ephemeral(
                interaction,
                "正股结构已保存。",
                delete_after=SUCCESS_DELETE_AFTER,
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)


class TargetsLogicEditModal(discord.ui.Modal):
    def __init__(self, controller: CardReviewCog, draft: ReviewDraft) -> None:
        super().__init__(
            title=f"编辑目标与逻辑 · {draft.draft_code}"[:45],
            timeout=300,
            custom_id=f"axis:review:targets:{draft.id.hex}:v{draft.version}",
        )
        self.controller = controller
        self.draft = draft
        self.pt1, pt1_label = _text_field(
            text="正股 PT1", default=_decimal_display(draft.stock_pt1), max_length=24
        )
        self.pt2, pt2_label = _text_field(
            text="正股 PT2", default=_decimal_display(draft.stock_pt2), max_length=24
        )
        self.pt3, pt3_label = _text_field(
            text="正股 PT3", default=_decimal_display(draft.stock_pt3), max_length=24
        )
        self.fib, fib_label = _text_field(
            text="Fib 0.618", default=_decimal_display(draft.fib_0618), max_length=24
        )
        self.thesis, thesis_label = _text_field(
            text="会员卡片交易逻辑",
            default=draft.public_thesis or "",
            description="可选；不要填写 Mentor 或来源",
            paragraph=True,
            max_length=600,
        )
        for item in (pt1_label, pt2_label, pt3_label, fib_label, thesis_label):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        try:
            await interaction.response.defer(ephemeral=True)
            updated = await self.controller.service.edit(
                self.draft.id,
                values=_edit_values(
                    self.draft,
                    stock_pt1=_optional_decimal(self.pt1.value),
                    stock_pt2=_optional_decimal(self.pt2.value),
                    stock_pt3=_optional_decimal(self.pt3.value),
                    fib_0618=_optional_decimal(self.fib.value),
                    public_thesis=_optional_text(self.thesis.value),
                    replace_plan=True,
                ),
                expected_version=self.draft.version,
                actor_user_id=interaction.user.id,
                interaction_id=interaction.id,
            )
            await self.controller.refresh(updated)
            await send_temporary_ephemeral(
                interaction,
                "目标和交易逻辑已保存，可重新生成图片。",
                delete_after=SUCCESS_DELETE_AFTER,
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)


_OPERATION_OPTIONS = (
    ("作为新订单发布", "NEW_TRADE:ENTRY:NONE", "没有可关联旧单时使用"),
    ("第一次加仓", "UPDATE_TRADE:ADD:FIRST", "操作后默认 1/4 仓位"),
    ("第二次加仓", "UPDATE_TRADE:ADD:SECOND", "操作后默认 1/2 仓位"),
    ("第三次加仓", "UPDATE_TRADE:ADD:THIRD", "操作后默认 3/4 仓位"),
    ("第四次加仓", "UPDATE_TRADE:ADD:FOURTH", "操作后默认满仓"),
    ("订单更新", "UPDATE_TRADE:UPDATE:NONE", "只更新成本、SL 或目标"),
    ("止盈一", "UPDATE_TRADE:TP1:NONE", "部分止盈"),
    ("止盈二", "UPDATE_TRADE:TP2:NONE", "部分止盈"),
    ("保留尾仓", "UPDATE_TRADE:RUNNER:NONE", "进入 Runner"),
    ("部分触发 SL", "UPDATE_TRADE:PARTIAL_SL:NONE", "部分减仓"),
    ("触发 SL", "UPDATE_TRADE:SL:NONE", "操作后默认清仓"),
    ("全部平仓", "UPDATE_TRADE:CLOSE:NONE", "操作后默认清仓"),
    ("取消订单", "UPDATE_TRADE:CANCEL:NONE", "操作后默认清仓"),
    ("滚仓", "UPDATE_TRADE:ROLL:NONE", "关联原订单后更换合约"),
)


class OperationSelect(discord.ui.Select):
    def __init__(self, controller: CardReviewCog, draft: ReviewDraft) -> None:
        self.controller = controller
        self.draft_id = draft.id
        current = f"{draft.intent}:{draft.action}:{draft.action_stage or 'NONE'}"
        super().__init__(
            placeholder="先选择这张卡片要做什么",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label=label,
                    value=value,
                    description=description,
                    default=value == current,
                )
                for label, value, description in _OPERATION_OPTIONS
            ],
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        try:
            await interaction.response.defer(ephemeral=True)
            current = await self.controller.service.get(self.draft_id)
            intent, action, stage = self.values[0].split(":", maxsplit=2)
            updated = await self.controller.service.select_operation(
                current.id,
                intent=intent,
                action=action,
                action_stage=stage,
                expected_version=current.version,
                actor_user_id=interaction.user.id,
                interaction_id=interaction.id,
            )
            await self.controller.refresh(updated)
            await send_temporary_ephemeral(
                interaction,
                "订单类型已保存；主审核卡片已刷新。",
                delete_after=SUCCESS_DELETE_AFTER,
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)


class SwingEditMenuView(discord.ui.View):
    def __init__(self, controller: CardReviewCog, draft: ReviewDraft) -> None:
        super().__init__(timeout=300)
        self.controller = controller
        self.draft_id = draft.id
        self.add_item(OperationSelect(controller, draft))

    async def _current(self, interaction: discord.Interaction) -> ReviewDraft | None:
        if not await self.controller.authorize(interaction):
            return None
        return await self.controller.service.get(self.draft_id)

    @discord.ui.button(label="编辑合约", style=discord.ButtonStyle.primary, row=1)
    async def contract(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if draft := await self._current(interaction):
            await interaction.response.send_modal(ContractEditModal(self.controller, draft))

    @discord.ui.button(label="价格 / 仓位", style=discord.ButtonStyle.primary, row=1)
    async def values(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if draft := await self._current(interaction):
            await interaction.response.send_modal(TradeValuesEditModal(self.controller, draft))

    @discord.ui.button(label="正股结构", style=discord.ButtonStyle.secondary, row=1)
    async def structure(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if draft := await self._current(interaction):
            await interaction.response.send_modal(StockStructureEditModal(self.controller, draft))

    @discord.ui.button(label="目标 / 逻辑", style=discord.ButtonStyle.secondary, row=1)
    async def targets(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if draft := await self._current(interaction):
            await interaction.response.send_modal(TargetsLogicEditModal(self.controller, draft))


class ShortTermEditModal(discord.ui.Modal):
    def __init__(self, controller: CardReviewCog, draft: ReviewDraft) -> None:
        super().__init__(
            title=f"Edit {draft.selected_category or 'Short-Term'} · {draft.draft_code}"[:45],
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
            label="Expiry · 0DTE / MM/DD / YYYY-MM-DD",
            default=_display(draft.expiry_input or draft.expiry),
            required=False,
            max_length=32,
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
            strike = _optional_decimal(self.strike.value)
            entry = _optional_decimal(self.entry_price.value)
            if strike is None or entry is None:
                raise ReviewValidationError("SHORT_TERM_FIELDS_REQUIRED")
            values = ShortTermDraftEdit(
                selected_category=self.draft.selected_category or "SHORT_TERM",
                ticker=self.ticker.value.strip().upper(),
                expiry_input=self.expiry.value.strip() or None,
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
                "追踪订单草稿已更新。",
                delete_after=SUCCESS_DELETE_AFTER,
            )
        except Exception as exc:
            await self.controller.handle_error(interaction, exc)


class SwingCloseEditModal(discord.ui.Modal):
    def __init__(self, controller: CardReviewCog, draft: ReviewDraft) -> None:
        super().__init__(title=f"Edit Swing Close · {draft.draft_code}"[:45], timeout=300)
        self.controller = controller
        self.draft = draft
        self.reference_price = discord.ui.TextInput(
            label="Close Reference Price · Optional",
            default=_decimal_display(draft.action_price),
            required=False,
            max_length=24,
        )
        self.add_item(self.reference_price)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        try:
            values = _edit_values(
                self.draft,
                intent="UPDATE_TRADE",
                action="CLOSE",
                action_stage=None,
                selected_category="SWING",
                action_price=_optional_decimal(self.reference_price.value),
                position_delta_eighths=None,
                position_after_eighths=0,
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
                "Swing 平仓参考价格已更新。",
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


class ExpirySelect(discord.ui.Select):
    def __init__(
        self,
        controller: CardReviewCog,
        draft: ReviewDraft,
        *,
        allow_shortcuts: bool = True,
        row: int = 1,
    ) -> None:
        self.controller = controller
        self.draft = draft
        options = []
        if allow_shortcuts:
            options.extend(
                [
                    discord.SelectOption(
                        label="0DTE",
                        value="ZERO_DTE",
                        description="仅选择今天存在的真实合约",
                        default=draft.expiry_precision == "ZERO_DTE",
                    ),
                    discord.SelectOption(
                        label="Nearest",
                        value="AUTO_NEAREST",
                        description="今天无合约时选择最近有效到期日",
                        default=draft.expiry_precision == "AUTO_NEAREST",
                    ),
                ]
            )
        limit = 23 if allow_shortcuts else 25
        for candidate in draft.expiry_candidates[:limit]:
            options.append(
                discord.SelectOption(
                    label=candidate.strftime("%m/%d/%Y"),
                    value=f"DATE:{candidate.isoformat()}",
                    description="Available expiration",
                    default=(
                        draft.expiry == candidate
                        and draft.expiry_precision not in {"ZERO_DTE", "AUTO_NEAREST"}
                    ),
                )
            )
        super().__init__(
            placeholder=(
                "EXPIRY · 0DTE / NEAREST / SELECT"
                if allow_shortcuts
                else "EXPIRY · SELECT AVAILABLE DATE"
            ),
            min_values=1,
            max_values=1,
            options=options,
            row=row,
            custom_id=f"axis:review:expiry:select:{draft.id.hex}:v{draft.version}",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            updated = await self.controller.service.select_expiry(
                self.draft.id,
                selection=self.values[0],
                expected_version=self.draft.version,
                actor_user_id=interaction.user.id,
                interaction_id=interaction.id,
            )
            await self.controller.refresh(updated)
            await send_temporary_ephemeral(
                interaction,
                "Expiry 已验证并保存。",
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
        category = draft.selected_category or draft.category_suggestion
        simple = category == "SHORT_TERM" or draft.swing_mode == "SIMPLE_TRACKED_SWING"
        if simple:
            close = draft.swing_mode == "SIMPLE_TRACKED_SWING" and draft.action == "CLOSE"
            if close:
                self.add_item(
                    ReviewChoiceSelect(controller, draft, kind="trade", choices=trade_choices)
                )
            elif category == "SHORT_TERM":
                self.add_item(ExpirySelect(controller, draft))
            elif draft.expiry_candidates:
                self.add_item(ExpirySelect(controller, draft, allow_shortcuts=False))
            button_row = 3 if close else 2
            buttons = (
                ("EDIT", discord.ButtonStyle.primary, "edit", button_row, self.edit),
                (
                    f"LOTTO · {'YES' if draft.is_lotto else 'NO'}",
                    (
                        discord.ButtonStyle.success
                        if draft.is_lotto
                        else discord.ButtonStyle.secondary
                    ),
                    "lotto",
                    button_row,
                    self.toggle_lotto,
                ),
                ("PUBLISH", discord.ButtonStyle.success, "approve", button_row, self.approve),
                ("DELETE", discord.ButtonStyle.danger, "delete", button_row, self.delete),
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
        if draft.expiry is None and draft.expiry_candidates:
            self.add_item(
                ExpirySelect(
                    controller,
                    draft,
                    allow_shortcuts=False,
                    row=2,
                )
            )
        else:
            self.add_item(
                ReviewChoiceSelect(controller, draft, kind="trade", choices=trade_choices)
            )
        buttons = (
            ("编辑必填项", discord.ButtonStyle.primary, "edit", 3, self.edit),
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
                (discord.ButtonStyle.success if draft.is_lotto else discord.ButtonStyle.secondary),
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
        if self.draft.swing_mode == "SIMPLE_TRACKED_SWING" and self.draft.action == "CLOSE":
            await interaction.response.send_modal(SwingCloseEditModal(self.controller, self.draft))
        elif (self.draft.selected_category or self.draft.category_suggestion) == "SHORT_TERM" or (
            self.draft.swing_mode == "SIMPLE_TRACKED_SWING"
        ):
            await interaction.response.send_modal(ShortTermEditModal(self.controller, self.draft))
        else:
            missing = missing_field_labels(publication_missing_fields(self.draft))
            await interaction.response.send_message(
                (
                    f"**编辑向导 · {self.draft.draft_code}**\n"
                    "先用下拉菜单选择订单类型，再按区域编辑。每个输入框只填写一个值。\n"
                    f"当前发布前必须补齐：{'、'.join(missing) if missing else '无'}"
                ),
                view=SwingEditMenuView(self.controller, self.draft),
                ephemeral=True,
                delete_after=300,
            )

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
        if self.category == TradeCategory.SWING.value:
            await self.controller.swing_tracking_service.refresh_active_prices(
                self.controller.guild_id
            )
            tracked = await self.controller.swing_tracking_service.active_positions(
                self.controller.guild_id
            )
            tracked_page = tracked[:10]
            embeds = [build_swing_active_embed(tracked_page)]
            if orders:
                legacy = build_active_orders_embed(self.category, orders)
                legacy.title = "当前 Legacy Swing 订单"
                embeds.append(legacy)
            page_view = SwingActivePaginationView(tracked) if len(tracked) > 10 else None
            await interaction.response.send_message(embeds=embeds, view=page_view, ephemeral=True)
            return
        await interaction.response.send_message(
            embed=build_active_orders_embed(self.category, orders),
            ephemeral=True,
        )


class SwingActivePaginationView(discord.ui.View):
    def __init__(self, trades: tuple, *, page: int = 0) -> None:
        super().__init__(timeout=300)
        self.trades = trades
        self.page = page
        self.pages = max(1, (len(trades) + 9) // 10)
        previous = discord.ui.Button(
            label="上一页",
            style=discord.ButtonStyle.secondary,
            disabled=page <= 0,
        )
        following = discord.ui.Button(
            label="下一页",
            style=discord.ButtonStyle.secondary,
            disabled=page >= self.pages - 1,
        )
        previous.callback = self.previous
        following.callback = self.following
        self.add_item(previous)
        self.add_item(following)

    def embed(self) -> discord.Embed:
        start = self.page * 10
        embed = build_swing_active_embed(self.trades[start : start + 10])
        embed.set_footer(text=f"AXIS · Page {self.page + 1}/{self.pages}")
        return embed

    async def previous(self, interaction: discord.Interaction) -> None:
        self.page = max(0, self.page - 1)
        await interaction.response.edit_message(
            embed=self.embed(), view=SwingActivePaginationView(self.trades, page=self.page)
        )

    async def following(self, interaction: discord.Interaction) -> None:
        self.page = min(self.pages - 1, self.page + 1)
        await interaction.response.edit_message(
            embed=self.embed(), view=SwingActivePaginationView(self.trades, page=self.page)
        )
