#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import ssl
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp
import certifi
from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings  # noqa: E402
from app.db.models import SourceMessage  # noqa: E402
from app.db.session import Database  # noqa: E402
from app.domain.enums import SourceKind, SourceStatus  # noqa: E402
from app.services.attachment_storage import LocalAttachmentStore  # noqa: E402
from app.services.signal_input import (  # noqa: E402
    IncomingAttachment,
    IncomingSignal,
    SignalInputService,
)


def _snapshot_payloads(payload: dict[str, Any]) -> list[dict[str, Any]]:
    snapshots = []
    for wrapper in payload.get("message_snapshots") or []:
        snapshot = wrapper.get("message") if isinstance(wrapper, dict) else None
        if isinstance(snapshot, dict):
            snapshots.append(snapshot)
    return snapshots


async def retry(message_id: int, settings_root: Path) -> int:
    settings = Settings.load(settings_root)
    database = Database(settings.require_database_url())
    try:
        async with database.session() as session:
            source = await session.scalar(
                select(SourceMessage).where(
                    SourceMessage.guild_id == settings.discord_guild_id,
                    SourceMessage.discord_message_id == message_id,
                    SourceMessage.source_kind == SourceKind.ANALYSIS.value,
                )
            )
        if source is None or source.status != SourceStatus.REJECTED.value:
            print("Analysis retry stopped: rejected source was not found.", file=sys.stderr)
            return 2

        api_url = (
            f"https://discord.com/api/v10/channels/{source.channel_id}/messages/{message_id}"
        )
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        async with aiohttp.ClientSession(connector=connector) as client:
            async with client.get(
                api_url,
                headers={"Authorization": f"Bot {settings.require_token()}"},
            ) as response:
                if response.status != 200:
                    print(
                        "Analysis retry stopped: Discord message is unavailable.",
                        file=sys.stderr,
                    )
                    return 2
                payload = await response.json()
            author = payload.get("author") or {}
            if str(author.get("id")) != str(source.submitted_by):
                print("Analysis retry stopped: source author differs.", file=sys.stderr)
                return 2

            texts = []
            direct_content = str(payload.get("content") or "").strip()
            if direct_content:
                texts.append(direct_content)
            attachment_payloads = list(payload.get("attachments") or [])
            for position, snapshot in enumerate(_snapshot_payloads(payload), start=1):
                forwarded_content = str(snapshot.get("content") or "").strip()
                if forwarded_content:
                    texts.append(f"[Forwarded message {position}]\n{forwarded_content}")
                attachment_payloads.extend(snapshot.get("attachments") or [])

            incoming_attachments = []
            seen_ids: set[int] = set()
            for item in attachment_payloads:
                attachment_id = int(item["id"])
                if attachment_id in seen_ids:
                    continue
                seen_ids.add(attachment_id)

                async def read(url: str = str(item["url"])) -> bytes:
                    async with client.get(url) as attachment_response:
                        attachment_response.raise_for_status()
                        return await attachment_response.read()

                incoming_attachments.append(
                    IncomingAttachment(
                        discord_attachment_id=attachment_id,
                        filename=str(item.get("filename") or "attachment"),
                        content_type=item.get("content_type"),
                        size_bytes=int(item["size"]),
                        read=read,
                    )
                )

            service = SignalInputService(
                database,
                LocalAttachmentStore(
                    settings.attachment_storage_path,
                    max_bytes=settings.max_attachment_bytes,
                ),
            )
            result = await service.retry_rejected(
                IncomingSignal(
                    guild_id=source.guild_id,
                    message_id=source.discord_message_id,
                    channel_id=source.channel_id,
                    submitted_by=source.submitted_by,
                    content="\n\n".join(texts),
                    received_at=datetime.fromisoformat(str(payload["timestamp"])),
                    attachments=tuple(incoming_attachments),
                    source_kind=SourceKind.ANALYSIS,
                )
            )
        print(f"message_id={message_id}")
        print(f"disposition={result.disposition.value}")
        print(f"reason_code={result.reason_code}")
        return 0 if result.disposition.value == "RECEIVED" else 2
    finally:
        await database.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Retry one rejected AXIS Analysis message.")
    parser.add_argument("--message-id", type=int, required=True)
    parser.add_argument("--settings-root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()
    try:
        return asyncio.run(retry(args.message_id, args.settings_root.resolve()))
    except Exception:
        print("Analysis retry failed; sensitive details were omitted.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
