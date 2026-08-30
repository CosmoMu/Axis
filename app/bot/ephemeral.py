import discord

SUCCESS_DELETE_AFTER = 4.0
ERROR_DELETE_AFTER = 12.0
PREVIEW_DELETE_AFTER = 60.0


async def send_temporary_ephemeral(
    interaction: discord.Interaction,
    content: str,
    *,
    delete_after: float,
) -> None:
    if interaction.response.is_done():
        message = await interaction.followup.send(
            content,
            ephemeral=True,
            wait=True,
        )
        if message is not None:
            await message.delete(delay=delete_after)
        return
    await interaction.response.send_message(
        content,
        ephemeral=True,
        delete_after=delete_after,
    )
