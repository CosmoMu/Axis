from __future__ import annotations

import discord

from app.bot.ephemeral import ERROR_DELETE_AFTER, send_temporary_ephemeral
from app.bot.personal_execution_cards import orders_embed, positions_embed


class PersonalExecutionControlView(discord.ui.View):
    def __init__(self, controller) -> None:
        super().__init__(timeout=None)
        self.controller = controller
        definitions = (
            ("AUTO FOLLOW", "auto-follow", discord.ButtonStyle.primary, self.auto_follow, 0),
            ("FOLLOW SCOPE", "scope", discord.ButtonStyle.secondary, self.follow_scope, 0),
            ("MANUAL SYNC", "manual-sync", discord.ButtonStyle.secondary, self.manual_sync, 0),
            ("AUTO RISK", "auto-risk", discord.ButtonStyle.primary, self.auto_risk, 0),
            ("REFRESH", "refresh", discord.ButtonStyle.secondary, self.refresh, 0),
            ("PAUSE ENTRIES", "pause-entries", discord.ButtonStyle.danger, self.pause_entries, 1),
            (
                "PAUSE MANAGEMENT",
                "pause-management",
                discord.ButtonStyle.danger,
                self.pause_management,
                1,
            ),
            ("POSITIONS", "positions", discord.ButtonStyle.secondary, self.positions, 2),
            ("ORDERS", "orders", discord.ButtonStyle.secondary, self.orders, 2),
            ("HISTORY", "history", discord.ButtonStyle.secondary, self.history, 2),
        )
        for label, action, style, callback, row in definitions:
            button = discord.ui.Button(
                label=label,
                style=style,
                custom_id=f"axis:personal-execution:{action}:v1",
                row=row,
            )
            button.callback = callback
            self.add_item(button)

    async def _toggle(self, interaction: discord.Interaction, name: str) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        await self.controller.service.update_toggle(name, actor_user_id=interaction.user.id)
        await self.controller.refresh_panel()
        await interaction.followup.send("Control updated.", ephemeral=True)

    async def auto_follow(self, interaction: discord.Interaction) -> None:
        await self._toggle(interaction, "auto_follow_enabled")

    async def follow_scope(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        await self.controller.service.cycle_follow_scope(actor_user_id=interaction.user.id)
        await self.controller.refresh_panel()
        await interaction.followup.send("Follow scope updated.", ephemeral=True)

    async def manual_sync(self, interaction: discord.Interaction) -> None:
        await self._toggle(interaction, "manual_position_sync_enabled")

    async def auto_risk(self, interaction: discord.Interaction) -> None:
        await self._toggle(interaction, "auto_risk_management_enabled")

    async def pause_entries(self, interaction: discord.Interaction) -> None:
        await self._toggle(interaction, "pause_new_entries")

    async def pause_management(self, interaction: discord.Interaction) -> None:
        await self._toggle(interaction, "pause_auto_management")

    async def refresh(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        await self.controller.reconcile_now()
        await interaction.followup.send("Broker reconciliation completed.", ephemeral=True)

    async def positions(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.send_message(
            embed=positions_embed(await self.controller.service.positions()),
            ephemeral=True,
        )

    async def orders(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        await interaction.response.send_message(
            embed=orders_embed(await self.controller.service.orders()),
            ephemeral=True,
        )

    async def history(self, interaction: discord.Interaction) -> None:
        if not await self.controller.authorize(interaction):
            return
        events = await self.controller.service.pending_events()
        lines = [f"{item.created_at:%m/%d %H:%M} · {item.event_type}" for item in events[-20:]]
        await interaction.response.send_message(
            "\n".join(lines) if lines else "No unacknowledged events.",
            ephemeral=True,
        )

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item,
    ) -> None:
        del item
        await send_temporary_ephemeral(
            interaction,
            f"Operation failed: {getattr(error, 'code', type(error).__name__)}",
            delete_after=ERROR_DELETE_AFTER,
        )
