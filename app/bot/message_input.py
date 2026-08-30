from __future__ import annotations

from dataclasses import dataclass

import discord

from app.services.signal_input import IncomingAttachment


@dataclass(frozen=True, slots=True)
class DiscordMessageInput:
    content: str
    attachments: tuple[IncomingAttachment, ...]


def extract_message_input(message: discord.Message) -> DiscordMessageInput:
    """Combine a Discord message and any forwarded snapshots into one safe input."""

    text_parts = [message.content.strip()] if message.content.strip() else []
    attachments = list(message.attachments)
    for position, snapshot in enumerate(message.message_snapshots, start=1):
        forwarded_text = snapshot.content.strip()
        if forwarded_text:
            text_parts.append(f"[Forwarded message {position}]\n{forwarded_text}")
        attachments.extend(snapshot.attachments)

    unique_attachments = []
    seen_attachment_ids: set[int] = set()
    for attachment in attachments:
        if attachment.id in seen_attachment_ids:
            continue
        seen_attachment_ids.add(attachment.id)
        unique_attachments.append(
            IncomingAttachment(
                discord_attachment_id=attachment.id,
                filename=attachment.filename,
                content_type=attachment.content_type,
                size_bytes=attachment.size,
                read=attachment.read,
            )
        )
    return DiscordMessageInput(
        content="\n\n".join(text_parts),
        attachments=tuple(unique_attachments),
    )
