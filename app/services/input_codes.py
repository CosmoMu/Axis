from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import InputCodeCounter

INPUT_CODE_PREFIXES = {
    "ANALYSIS": "A",
    "SIGNAL": "S",
}


async def next_input_code(session: AsyncSession, guild_id: int, input_kind: str) -> str:
    """Allocate a short, monotonic manager-facing input code inside the transaction."""

    prefix = INPUT_CODE_PREFIXES[input_kind]
    counter = await session.scalar(
        select(InputCodeCounter)
        .where(
            InputCodeCounter.guild_id == guild_id,
            InputCodeCounter.input_kind == input_kind,
        )
        .with_for_update()
    )
    if counter is None:
        number = 1
        session.add(
            InputCodeCounter(
                guild_id=guild_id,
                input_kind=input_kind,
                next_value=2,
            )
        )
    else:
        number = counter.next_value
        counter.next_value += 1
    await session.flush()
    return f"{prefix}-{number:05d}"
