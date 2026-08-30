from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Mentor, MentorAlias, Trade
from app.db.session import Database
from app.domain.enums import TradeState


class MentorError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class MentorValidationError(MentorError):
    pass


@dataclass(frozen=True, slots=True)
class MentorTrade:
    trade_id: uuid.UUID
    public_trade_id: str
    ticker: str
    state: str


@dataclass(frozen=True, slots=True)
class MentorSnapshot:
    id: uuid.UUID
    guild_id: int
    name: str
    short_code: str
    aliases: tuple[str, ...]
    is_active: bool
    active_trades: tuple[MentorTrade, ...]
    historical_trades: tuple[MentorTrade, ...]


def _normalize(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def _clean_values(
    name: str, short_code: str, aliases: list[str] | tuple[str, ...]
) -> tuple[str, str, tuple[str, ...]]:
    cleaned_name = " ".join(name.strip().split())
    cleaned_code = short_code.strip().upper()
    if not 1 <= len(cleaned_name) <= 100:
        raise MentorValidationError("MENTOR_NAME_INVALID")
    if not 1 <= len(cleaned_code) <= 24 or any(
        character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for character in cleaned_code
    ):
        raise MentorValidationError("MENTOR_CODE_INVALID")
    cleaned_aliases: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        cleaned = " ".join(alias.strip().split())
        normalized = _normalize(cleaned)
        if not cleaned or len(cleaned) > 100 or normalized in seen:
            continue
        seen.add(normalized)
        cleaned_aliases.append(cleaned)
    return cleaned_name, cleaned_code, tuple(cleaned_aliases)


class MentorManagementService:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def list(self, guild_id: int) -> list[MentorSnapshot]:
        async with self.database.session() as session:
            mentors = (
                await session.scalars(
                    select(Mentor)
                    .where(Mentor.guild_id == guild_id)
                    .order_by(Mentor.is_active.desc(), Mentor.name)
                )
            ).all()
            return [await self._snapshot(session, mentor) for mentor in mentors]

    async def get(self, mentor_id: uuid.UUID) -> MentorSnapshot:
        async with self.database.session() as session:
            mentor = await session.get(Mentor, mentor_id)
            if mentor is None:
                raise MentorValidationError("MENTOR_NOT_FOUND")
            return await self._snapshot(session, mentor)

    async def create(
        self,
        guild_id: int,
        *,
        name: str,
        short_code: str,
        aliases: list[str] | tuple[str, ...],
        actor_user_id: int,
        interaction_id: int | None,
    ) -> MentorSnapshot:
        cleaned_name, cleaned_code, cleaned_aliases = _clean_values(name, short_code, aliases)
        async with self.database.session() as session:
            mentor = Mentor(
                guild_id=guild_id,
                name=cleaned_name,
                short_code=cleaned_code,
                is_active=True,
            )
            session.add(mentor)
            await session.flush()
            self._replace_aliases(session, mentor, cleaned_aliases)
            self._audit(
                session,
                mentor=mentor,
                actor_user_id=actor_user_id,
                interaction_id=interaction_id,
                action_type="MENTOR_CREATED",
                before=None,
            )
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise MentorValidationError("MENTOR_ALREADY_EXISTS") from exc
            return await self._snapshot(session, mentor)

    async def edit(
        self,
        mentor_id: uuid.UUID,
        *,
        name: str,
        short_code: str,
        aliases: list[str] | tuple[str, ...],
        actor_user_id: int,
        interaction_id: int | None,
    ) -> MentorSnapshot:
        cleaned_name, cleaned_code, cleaned_aliases = _clean_values(name, short_code, aliases)
        async with self.database.session() as session:
            mentor = await session.scalar(
                select(Mentor).where(Mentor.id == mentor_id).with_for_update()
            )
            if mentor is None:
                raise MentorValidationError("MENTOR_NOT_FOUND")
            before = self._mentor_payload(mentor)
            mentor.name = cleaned_name
            mentor.short_code = cleaned_code
            await session.execute(
                MentorAlias.__table__.delete().where(MentorAlias.mentor_id == mentor.id)
            )
            self._replace_aliases(session, mentor, cleaned_aliases)
            self._audit(
                session,
                mentor=mentor,
                actor_user_id=actor_user_id,
                interaction_id=interaction_id,
                action_type="MENTOR_EDITED",
                before=before,
            )
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise MentorValidationError("MENTOR_ALREADY_EXISTS") from exc
            return await self._snapshot(session, mentor)

    async def set_active(
        self,
        mentor_id: uuid.UUID,
        *,
        is_active: bool,
        actor_user_id: int,
        interaction_id: int | None,
    ) -> MentorSnapshot:
        async with self.database.session() as session:
            mentor = await session.scalar(
                select(Mentor).where(Mentor.id == mentor_id).with_for_update()
            )
            if mentor is None:
                raise MentorValidationError("MENTOR_NOT_FOUND")
            if mentor.is_active != is_active:
                before = self._mentor_payload(mentor)
                mentor.is_active = is_active
                self._audit(
                    session,
                    mentor=mentor,
                    actor_user_id=actor_user_id,
                    interaction_id=interaction_id,
                    action_type=("MENTOR_REACTIVATED" if is_active else "MENTOR_DEACTIVATED"),
                    before=before,
                )
                await session.commit()
            return await self._snapshot(session, mentor)

    async def reassign_trade(
        self,
        trade_id: uuid.UUID,
        *,
        mentor_id: uuid.UUID,
        actor_user_id: int,
        interaction_id: int | None,
    ) -> MentorSnapshot:
        async with self.database.session() as session:
            trade = await session.scalar(
                select(Trade).where(Trade.id == trade_id).with_for_update()
            )
            mentor = await session.get(Mentor, mentor_id)
            if trade is None:
                raise MentorValidationError("TRADE_NOT_FOUND")
            if mentor is None or mentor.guild_id != trade.guild_id or not mentor.is_active:
                raise MentorValidationError("MENTOR_NOT_FOUND")
            before_id = trade.mentor_id
            trade.mentor_id = mentor.id
            trade.version += 1
            session.add(
                AuditLog(
                    guild_id=trade.guild_id,
                    actor_user_id=actor_user_id,
                    action_type="TRADE_MENTOR_REASSIGNED",
                    entity_type="trade",
                    entity_id=str(trade.id),
                    before_json={"mentor_id": str(before_id)},
                    after_json={"mentor_id": str(mentor.id)},
                    discord_interaction_id=interaction_id,
                )
            )
            await session.commit()
            return await self._snapshot(session, mentor)

    @staticmethod
    def _replace_aliases(session: AsyncSession, mentor: Mentor, aliases: tuple[str, ...]) -> None:
        for alias in aliases:
            session.add(
                MentorAlias(
                    guild_id=mentor.guild_id,
                    mentor_id=mentor.id,
                    alias=alias,
                    normalized_alias=_normalize(alias),
                )
            )

    @staticmethod
    def _mentor_payload(mentor: Mentor) -> dict[str, object]:
        return {
            "name": mentor.name,
            "short_code": mentor.short_code,
            "is_active": mentor.is_active,
        }

    @classmethod
    def _audit(
        cls,
        session: AsyncSession,
        *,
        mentor: Mentor,
        actor_user_id: int,
        interaction_id: int | None,
        action_type: str,
        before: dict[str, object] | None,
    ) -> None:
        session.add(
            AuditLog(
                guild_id=mentor.guild_id,
                actor_user_id=actor_user_id,
                action_type=action_type,
                entity_type="mentor",
                entity_id=str(mentor.id),
                before_json=before,
                after_json=cls._mentor_payload(mentor),
                discord_interaction_id=interaction_id,
            )
        )

    @staticmethod
    async def _snapshot(session: AsyncSession, mentor: Mentor) -> MentorSnapshot:
        aliases = tuple(
            (
                await session.scalars(
                    select(MentorAlias.alias)
                    .where(MentorAlias.mentor_id == mentor.id)
                    .order_by(MentorAlias.alias)
                )
            ).all()
        )
        trades = (
            await session.scalars(
                select(Trade)
                .where(Trade.mentor_id == mentor.id)
                .order_by(Trade.updated_at.desc(), Trade.public_trade_id)
                .limit(50)
            )
        ).all()
        snapshots = tuple(
            MentorTrade(
                trade_id=trade.id,
                public_trade_id=trade.public_trade_id,
                ticker=trade.ticker,
                state=trade.state,
            )
            for trade in trades
        )
        active_states = {TradeState.ACTIVE.value, TradeState.RUNNER.value}
        return MentorSnapshot(
            id=mentor.id,
            guild_id=mentor.guild_id,
            name=mentor.name,
            short_code=mentor.short_code,
            aliases=aliases,
            is_active=mentor.is_active,
            active_trades=tuple(item for item in snapshots if item.state in active_states),
            historical_trades=tuple(item for item in snapshots if item.state not in active_states),
        )
