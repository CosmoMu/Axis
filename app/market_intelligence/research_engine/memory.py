"""Point-in-time-safe research memory backed by the AXIS database."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import desc, select

from app.db.models import ResearchReflection
from app.db.session import Database


class ResearchMemoryStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def load(
        self,
        *,
        ticker: str,
        as_of: datetime,
        same_ticker_limit: int,
        cross_ticker_limit: int,
    ) -> tuple[dict[str, object], ...]:
        if same_ticker_limit <= 0 and cross_ticker_limit <= 0:
            return ()
        async with self.database.session() as session:
            same_rows = (
                (
                    await session.execute(
                        select(ResearchReflection)
                        .where(
                            ResearchReflection.ticker == ticker,
                            ResearchReflection.resolution_timestamp <= as_of,
                        )
                        .order_by(desc(ResearchReflection.resolution_timestamp))
                        .limit(max(0, same_ticker_limit))
                    )
                )
                .scalars()
                .all()
            )
            cross_rows = (
                (
                    await session.execute(
                        select(ResearchReflection)
                        .where(
                            ResearchReflection.ticker != ticker,
                            ResearchReflection.resolution_timestamp <= as_of,
                            ResearchReflection.reflection_json.is_not(None),
                        )
                        .order_by(desc(ResearchReflection.resolution_timestamp))
                        .limit(max(0, cross_ticker_limit))
                    )
                )
                .scalars()
                .all()
            )
        return tuple(
            {
                "ticker": row.ticker,
                "horizon_trading_days": row.horizon_trading_days,
                "resolution_timestamp": row.resolution_timestamp.isoformat(),
                "reflection": row.reflection_json,
            }
            for row in (*same_rows, *cross_rows)
        )
