from __future__ import annotations

import logging

import discord
from discord.ext import commands

logger = logging.getLogger(__name__)


async def delete_owned_bot_message(
    bot: commands.Bot,
    *,
    channel_id: int,
    message_id: int,
) -> bool:
    """Delete one exact AXIS BOT message.

    True means the message is now absent and its database reference may be
    released. False keeps the reference so a later sweep can retry safely.
    """

    bot_user = bot.user
    if bot_user is None:
        return False
    try:
        channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        fetch_message = getattr(channel, "fetch_message", None)
        if fetch_message is None:
            return False
        message = await fetch_message(message_id)
    except discord.NotFound:
        return True
    except discord.HTTPException as exc:
        logger.warning(
            "event=review_cleanup_fetch_failed channel_id=%s message_id=%s status=%s",
            channel_id,
            message_id,
            exc.status,
        )
        return False

    if message.author.id != bot_user.id:
        logger.warning(
            "event=review_cleanup_skipped_not_owned channel_id=%s message_id=%s",
            channel_id,
            message_id,
        )
        return False
    try:
        await message.delete()
    except discord.NotFound:
        return True
    except discord.HTTPException as exc:
        logger.warning(
            "event=review_cleanup_delete_failed channel_id=%s message_id=%s status=%s",
            channel_id,
            message_id,
            exc.status,
        )
        return False
    return True
