from __future__ import annotations

import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    AccessApplication,
    AuditLog,
    GuildConfig,
    MembershipTrial,
    NewcomerProfile,
    NewcomerRiskFlag,
    utc_now,
)
from app.db.session import Database
from app.domain.enums import AccessApplicationStatus, EntitlementType
from app.services.membership_access import MembershipAcknowledgementService

DISCOVERY_SOURCES = {
    "FRIEND_REFERRAL": "朋友推荐",
    "X_SOCIAL_MEDIA": "X / 社交媒体",
    "DISCORD": "Discord",
    "ONLINE_COMMUNITY": "网络社区",
    "OTHER": "其他",
}
INTERESTS = {"SHORT_TERM", "SWING", "LEAPS", "MARKET_ANALYSIS"}
INTEREST_LABELS = {
    "SHORT_TERM": "短线",
    "SWING": "波段",
    "LEAPS": "长期",
    "MARKET_ANALYSIS": "市场分析",
}


class NewcomerAccessError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ApplicationSnapshot:
    id: uuid.UUID
    guild_id: int
    user_id: int
    username: str
    display_name: str
    discovery_source: str
    referred_by: str | None
    interests: tuple[str, ...]
    risk_acknowledged: bool
    community_rules_acknowledged: bool
    status: str
    submitted_at: datetime
    reviewed_at: datetime | None
    reviewed_by_user_id: int | None
    review_note: str | None
    review_channel_id: int | None
    review_message_id: int | None
    lobby_welcome_message_id: int | None
    member_lounge_welcome_message_id: int | None


@dataclass(frozen=True, slots=True)
class ProfileSnapshot:
    guild_id: int
    user_id: int
    username: str
    display_name: str
    first_joined_at: datetime
    last_joined_at: datetime
    join_count: int
    approved_at: datetime | None
    role_sync_status: str

    @property
    def approved(self) -> bool:
        return self.approved_at is not None


@dataclass(frozen=True, slots=True)
class RiskFlagSnapshot:
    id: uuid.UUID
    user_id: int
    application_id: uuid.UUID | None
    risk_code: str
    severity: str
    details: str | None
    occurrence_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None


@dataclass(frozen=True, slots=True)
class RiskScanResult:
    flags: tuple[RiskFlagSnapshot, ...]
    created_codes: tuple[str, ...]
    resolved_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NewcomerSecurityMetrics:
    newcomers: int
    pending_applications: int
    flagged_applications: int
    high_risk_newcomers: int
    approved_today: int
    rejected_today: int

    @property
    def health(self) -> str:
        return "ATTENTION" if self.high_risk_newcomers else "HEALTHY"


class NewcomerAccessService:
    def __init__(
        self,
        database: Database,
        acknowledgements: MembershipAcknowledgementService,
    ) -> None:
        self.database = database
        self.acknowledgements = acknowledgements

    async def gate_activated_at(self, guild_id: int) -> datetime | None:
        async with self.database.session() as session:
            value = await session.scalar(
                select(GuildConfig.newcomer_gate_activated_at).where(
                    GuildConfig.guild_id == guild_id
                )
            )
            return _aware(value) if value is not None else None

    async def activate_gate(self, guild_id: int, *, actor_user_id: int) -> datetime:
        now = utc_now()
        async with self.database.session() as session:
            config = await session.get(GuildConfig, guild_id, with_for_update=True)
            if config is None:
                raise NewcomerAccessError("GUILD_CONFIG_NOT_FOUND")
            if config.newcomer_gate_activated_at is None:
                config.newcomer_gate_activated_at = now
                self._audit(
                    session,
                    guild_id=guild_id,
                    actor_user_id=actor_user_id,
                    action="NEWCOMER_GATE_ACTIVATED",
                    entity_type="guild_config",
                    entity_id=str(guild_id),
                    after={"activated_at": now.isoformat()},
                )
                await session.commit()
            return _aware(config.newcomer_gate_activated_at)

    async def profile(self, guild_id: int, user_id: int) -> ProfileSnapshot | None:
        async with self.database.session() as session:
            row = await session.get(NewcomerProfile, (guild_id, user_id))
            return self._profile_snapshot(row) if row is not None else None

    async def register_join(
        self,
        guild_id: int,
        user_id: int,
        *,
        username: str,
        display_name: str,
        joined_at: datetime | None = None,
    ) -> ProfileSnapshot:
        now = _aware(joined_at or utc_now())
        async with self.database.session() as session:
            row = await session.get(
                NewcomerProfile,
                (guild_id, user_id),
                with_for_update=True,
            )
            if row is None:
                row = NewcomerProfile(
                    guild_id=guild_id,
                    discord_user_id=user_id,
                    discord_username_snapshot=username[:100],
                    discord_display_name_snapshot=display_name[:100],
                    first_joined_at=now,
                    last_joined_at=now,
                    join_count=1,
                )
                session.add(row)
            else:
                row.discord_username_snapshot = username[:100]
                row.discord_display_name_snapshot = display_name[:100]
                row.last_joined_at = now
                row.join_count += 1
            await session.commit()
            return self._profile_snapshot(row)

    async def baseline_approved_user(
        self,
        guild_id: int,
        user_id: int,
        *,
        username: str,
        display_name: str,
        joined_at: datetime,
        actor_user_id: int,
    ) -> bool:
        """Mark a pre-gate production user approved without granting a Trial."""
        now = utc_now()
        async with self.database.session() as session:
            row = await session.get(
                NewcomerProfile,
                (guild_id, user_id),
                with_for_update=True,
            )
            if row is not None:
                return False
            row = NewcomerProfile(
                guild_id=guild_id,
                discord_user_id=user_id,
                discord_username_snapshot=username[:100],
                discord_display_name_snapshot=display_name[:100],
                first_joined_at=_aware(joined_at),
                last_joined_at=_aware(joined_at),
                join_count=1,
                approved_at=now,
            )
            session.add(row)
            session.add(
                AuditLog(
                    guild_id=guild_id,
                    actor_user_id=actor_user_id,
                    action_type="EXISTING_PRODUCTION_USER_BASELINED",
                    entity_type="newcomer_profile",
                    entity_id=str(user_id),
                    after_json={"approved_at": now.isoformat(), "free_trial_created": False},
                )
            )
            await session.commit()
            return True

    async def is_approved(self, guild_id: int, user_id: int) -> bool:
        async with self.database.session() as session:
            approved = await session.scalar(
                select(NewcomerProfile.approved_at).where(
                    NewcomerProfile.guild_id == guild_id,
                    NewcomerProfile.discord_user_id == user_id,
                )
            )
            return approved is not None

    async def application_state(self, guild_id: int, user_id: int) -> str:
        if await self.is_approved(guild_id, user_id):
            return AccessApplicationStatus.APPROVED.value
        async with self.database.session() as session:
            status = await session.scalar(
                select(AccessApplication.status)
                .where(
                    AccessApplication.guild_id == guild_id,
                    AccessApplication.discord_user_id == user_id,
                )
                .order_by(AccessApplication.submitted_at.desc())
                .limit(1)
            )
            return status or "ELIGIBLE"

    async def submit_application(
        self,
        guild_id: int,
        user_id: int,
        *,
        username: str,
        display_name: str,
        discovery_source: str,
        referred_by: str | None,
        interests: tuple[str, ...],
        interaction_id: int | None,
    ) -> ApplicationSnapshot:
        if discovery_source not in DISCOVERY_SOURCES:
            raise NewcomerAccessError("DISCOVERY_SOURCE_INVALID")
        normalized_interests = tuple(dict.fromkeys(interests))
        if not normalized_interests or any(item not in INTERESTS for item in normalized_interests):
            raise NewcomerAccessError("INTERESTS_INVALID")
        await self.acknowledgements.accept_risk(
            guild_id,
            user_id,
            interaction_id=interaction_id,
        )
        now = utc_now()
        async with self.database.session() as session:
            profile = await session.get(
                NewcomerProfile,
                (guild_id, user_id),
                with_for_update=True,
            )
            if profile is not None and profile.approved_at is not None:
                raise NewcomerAccessError("APPLICATION_ALREADY_APPROVED")
            existing = await session.scalar(
                select(AccessApplication).where(
                    AccessApplication.guild_id == guild_id,
                    AccessApplication.discord_user_id == user_id,
                    AccessApplication.status.in_(
                        {
                            AccessApplicationStatus.PENDING.value,
                            AccessApplicationStatus.FLAGGED.value,
                        }
                    ),
                )
            )
            if existing is not None:
                raise NewcomerAccessError("APPLICATION_ALREADY_PENDING")
            if profile is None:
                profile = NewcomerProfile(
                    guild_id=guild_id,
                    discord_user_id=user_id,
                    discord_username_snapshot=username[:100],
                    discord_display_name_snapshot=display_name[:100],
                    first_joined_at=now,
                    last_joined_at=now,
                    join_count=1,
                )
                session.add(profile)
            application = AccessApplication(
                guild_id=guild_id,
                discord_user_id=user_id,
                discord_username_snapshot=username[:100],
                discord_display_name_snapshot=display_name[:100],
                discovery_source=discovery_source,
                referred_by_text=(referred_by or "").strip()[:200] or None,
                interests=list(normalized_interests),
                risk_acknowledged=True,
                community_rules_acknowledged=True,
                status=AccessApplicationStatus.PENDING.value,
                submitted_at=now,
            )
            session.add(application)
            await session.flush()
            self._audit(
                session,
                guild_id=guild_id,
                actor_user_id=user_id,
                action="APPLICATION_SUBMITTED",
                entity_type="access_application",
                entity_id=str(application.id),
                interaction_id=interaction_id,
                after={"status": application.status},
            )
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise NewcomerAccessError("APPLICATION_ALREADY_PENDING") from exc
            return self._application_snapshot(application)

    async def get_application(self, application_id: uuid.UUID) -> ApplicationSnapshot | None:
        async with self.database.session() as session:
            row = await session.get(AccessApplication, application_id)
            return self._application_snapshot(row) if row is not None else None

    async def open_applications(self, guild_id: int) -> tuple[ApplicationSnapshot, ...]:
        async with self.database.session() as session:
            rows = (
                await session.scalars(
                    select(AccessApplication)
                    .where(
                        AccessApplication.guild_id == guild_id,
                        AccessApplication.status.in_(
                            {
                                AccessApplicationStatus.PENDING.value,
                                AccessApplicationStatus.FLAGGED.value,
                            }
                        ),
                    )
                    .order_by(AccessApplication.submitted_at)
                )
            ).all()
            return tuple(self._application_snapshot(row) for row in rows)

    async def approved_applications_without_trial(
        self, guild_id: int
    ) -> tuple[ApplicationSnapshot, ...]:
        """Return approved applications whose automatic Trial still needs recovery.

        Approval and Trial creation are intentionally protected by separate durable
        records. This query lets reconciliation finish the workflow after a process
        interruption without granting a Trial to pre-gate baseline users, who do not
        have an approved application.
        """
        async with self.database.session() as session:
            rows = (
                await session.scalars(
                    select(AccessApplication)
                    .outerjoin(
                        MembershipTrial,
                        (
                            MembershipTrial.discord_user_id
                            == AccessApplication.discord_user_id
                        )
                        & (
                            MembershipTrial.trial_type
                            == EntitlementType.FREE_TRIAL.value
                        ),
                    )
                    .where(
                        AccessApplication.guild_id == guild_id,
                        AccessApplication.status
                        == AccessApplicationStatus.APPROVED.value,
                        MembershipTrial.id.is_(None),
                    )
                    .order_by(AccessApplication.reviewed_at)
                )
            ).all()
            return tuple(self._application_snapshot(row) for row in rows)

    async def approved_applications_pending_welcome(
        self, guild_id: int
    ) -> tuple[ApplicationSnapshot, ...]:
        async with self.database.session() as session:
            rows = (
                await session.scalars(
                    select(AccessApplication)
                    .where(
                        AccessApplication.guild_id == guild_id,
                        AccessApplication.status
                        == AccessApplicationStatus.APPROVED.value,
                        (
                            AccessApplication.lobby_welcome_message_id.is_(None)
                            | AccessApplication.member_lounge_welcome_message_id.is_(None)
                        ),
                    )
                    .order_by(AccessApplication.reviewed_at)
                )
            ).all()
            return tuple(self._application_snapshot(row) for row in rows)

    async def attach_approval_welcome_message(
        self,
        application_id: uuid.UUID,
        *,
        destination: str,
        message_id: int,
        actor_user_id: int,
    ) -> bool:
        field_by_destination = {
            "LOBBY": "lobby_welcome_message_id",
            "MEMBER_LOUNGE": "member_lounge_welcome_message_id",
        }
        field = field_by_destination.get(destination.strip().upper())
        if field is None:
            raise NewcomerAccessError("WELCOME_DESTINATION_INVALID")
        async with self.database.session() as session:
            row = await session.get(AccessApplication, application_id, with_for_update=True)
            if row is None:
                raise NewcomerAccessError("APPLICATION_NOT_FOUND")
            if getattr(row, field) is not None:
                return False
            setattr(row, field, message_id)
            self._audit(
                session,
                guild_id=row.guild_id,
                actor_user_id=actor_user_id,
                action="NEW_MEMBER_WELCOME_SENT",
                entity_type="access_application",
                entity_id=str(row.id),
                after={"destination": destination.strip().upper(), "message_id": message_id},
            )
            await session.commit()
            return True

    async def previous_application_status(
        self,
        guild_id: int,
        user_id: int,
        *,
        exclude_id: uuid.UUID,
    ) -> str | None:
        async with self.database.session() as session:
            return await session.scalar(
                select(AccessApplication.status)
                .where(
                    AccessApplication.guild_id == guild_id,
                    AccessApplication.discord_user_id == user_id,
                    AccessApplication.id != exclude_id,
                )
                .order_by(AccessApplication.submitted_at.desc())
                .limit(1)
            )

    async def has_trial_history(self, user_id: int) -> bool:
        async with self.database.session() as session:
            trial = await session.scalar(
                select(MembershipTrial.id).where(
                    MembershipTrial.discord_user_id == user_id,
                    MembershipTrial.trial_type == EntitlementType.FREE_TRIAL.value,
                )
            )
            return trial is not None

    async def active_risk_flags(self, guild_id: int, user_id: int) -> tuple[RiskFlagSnapshot, ...]:
        async with self.database.session() as session:
            rows = (
                await session.scalars(
                    select(NewcomerRiskFlag)
                    .where(
                        NewcomerRiskFlag.guild_id == guild_id,
                        NewcomerRiskFlag.discord_user_id == user_id,
                        NewcomerRiskFlag.resolved_at.is_(None),
                    )
                    .order_by(NewcomerRiskFlag.severity.desc(), NewcomerRiskFlag.risk_code)
                )
            ).all()
            return tuple(NewcomerRiskScanner._snapshot(row) for row in rows)

    async def record_role_event(
        self,
        guild_id: int,
        user_id: int,
        *,
        action: str,
        actor_user_id: int,
        role_name: str,
    ) -> None:
        async with self.database.session() as session:
            self._audit(
                session,
                guild_id=guild_id,
                actor_user_id=actor_user_id,
                action=action,
                entity_type="discord_role",
                entity_id=str(user_id),
                after={"role": role_name},
            )
            await session.commit()

    async def attach_review_message(
        self,
        application_id: uuid.UUID,
        *,
        channel_id: int,
        message_id: int,
    ) -> None:
        async with self.database.session() as session:
            row = await session.get(AccessApplication, application_id)
            if row is None:
                raise NewcomerAccessError("APPLICATION_NOT_FOUND")
            row.review_channel_id = channel_id
            row.review_message_id = message_id
            await session.commit()

    async def review(
        self,
        application_id: uuid.UUID,
        *,
        action: str,
        actor_user_id: int,
        interaction_id: int | None,
        note: str | None = None,
    ) -> ApplicationSnapshot:
        target = action.strip().upper()
        if target not in {
            AccessApplicationStatus.APPROVED.value,
            AccessApplicationStatus.REJECTED.value,
            AccessApplicationStatus.FLAGGED.value,
        }:
            raise NewcomerAccessError("APPLICATION_REVIEW_ACTION_INVALID")
        now = utc_now()
        async with self.database.session() as session:
            row = await session.get(AccessApplication, application_id, with_for_update=True)
            if row is None:
                raise NewcomerAccessError("APPLICATION_NOT_FOUND")
            if row.status == target:
                return self._application_snapshot(row)
            allowed = row.status == AccessApplicationStatus.PENDING.value or (
                row.status == AccessApplicationStatus.FLAGGED.value
                and target
                in {
                    AccessApplicationStatus.APPROVED.value,
                    AccessApplicationStatus.REJECTED.value,
                }
            )
            if not allowed:
                raise NewcomerAccessError("APPLICATION_REVIEW_STATE_INVALID")
            before = row.status
            row.status = target
            row.reviewed_at = now
            row.reviewed_by_user_id = actor_user_id
            row.review_note = (note or "").strip()[:1000] or None
            if target == AccessApplicationStatus.APPROVED.value:
                profile = await session.get(
                    NewcomerProfile,
                    (row.guild_id, row.discord_user_id),
                    with_for_update=True,
                )
                if profile is None:
                    raise NewcomerAccessError("NEWCOMER_PROFILE_NOT_FOUND")
                profile.approved_at = profile.approved_at or now
                profile.role_sync_status = "PENDING"
                profile.last_role_error = None
            action_name = {
                "APPROVED": "APPLICATION_APPROVED",
                "REJECTED": "APPLICATION_REJECTED",
                "FLAGGED": "APPLICATION_FLAGGED",
            }[target]
            self._audit(
                session,
                guild_id=row.guild_id,
                actor_user_id=actor_user_id,
                action=action_name,
                entity_type="access_application",
                entity_id=str(row.id),
                interaction_id=interaction_id,
                before={"status": before},
                after={"status": target},
            )
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise NewcomerAccessError("APPLICATION_ALREADY_APPROVED") from exc
            return self._application_snapshot(row)

    async def mark_role_sync(
        self,
        guild_id: int,
        user_id: int,
        *,
        status: str,
        error_code: str | None = None,
        actor_user_id: int,
    ) -> None:
        if status not in {"SYNCED", "PENDING", "FAILED"}:
            raise ValueError("ROLE_SYNC_STATUS_INVALID")
        async with self.database.session() as session:
            profile = await session.get(NewcomerProfile, (guild_id, user_id))
            if profile is None:
                return
            before = profile.role_sync_status
            profile.role_sync_status = status
            profile.last_role_error = error_code[:100] if error_code else None
            if before != status:
                action = "ROLE_SYNC_RECONCILED" if status == "SYNCED" else "ROLE_SYNC_FAILED"
                self._audit(
                    session,
                    guild_id=guild_id,
                    actor_user_id=actor_user_id,
                    action=action,
                    entity_type="newcomer_profile",
                    entity_id=str(user_id),
                    before={"role_sync_status": before},
                    after={"role_sync_status": status, "error": error_code},
                )
            await session.commit()

    async def metrics(
        self, guild_id: int, *, now: datetime | None = None
    ) -> NewcomerSecurityMetrics:
        current = _aware(now or utc_now())
        day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
        async with self.database.session() as session:
            newcomers = await session.scalar(
                select(func.count())
                .select_from(NewcomerProfile)
                .where(
                    NewcomerProfile.guild_id == guild_id,
                    NewcomerProfile.approved_at.is_(None),
                )
            )
            pending = await session.scalar(
                select(func.count())
                .select_from(AccessApplication)
                .where(
                    AccessApplication.guild_id == guild_id,
                    AccessApplication.status == AccessApplicationStatus.PENDING.value,
                )
            )
            flagged = await session.scalar(
                select(func.count())
                .select_from(AccessApplication)
                .where(
                    AccessApplication.guild_id == guild_id,
                    AccessApplication.status == AccessApplicationStatus.FLAGGED.value,
                )
            )
            high_risk = await session.scalar(
                select(func.count(func.distinct(NewcomerRiskFlag.discord_user_id)))
                .join(
                    NewcomerProfile,
                    (NewcomerProfile.guild_id == NewcomerRiskFlag.guild_id)
                    & (
                        NewcomerProfile.discord_user_id
                        == NewcomerRiskFlag.discord_user_id
                    ),
                )
                .where(
                    NewcomerRiskFlag.guild_id == guild_id,
                    NewcomerRiskFlag.severity == "HIGH",
                    NewcomerRiskFlag.resolved_at.is_(None),
                    NewcomerProfile.approved_at.is_(None),
                )
            )
            approved = await session.scalar(
                select(func.count())
                .select_from(AccessApplication)
                .where(
                    AccessApplication.guild_id == guild_id,
                    AccessApplication.status == AccessApplicationStatus.APPROVED.value,
                    AccessApplication.reviewed_at >= day_start,
                )
            )
            rejected = await session.scalar(
                select(func.count())
                .select_from(AccessApplication)
                .where(
                    AccessApplication.guild_id == guild_id,
                    AccessApplication.status == AccessApplicationStatus.REJECTED.value,
                    AccessApplication.reviewed_at >= day_start,
                )
            )
        return NewcomerSecurityMetrics(
            int(newcomers or 0),
            int(pending or 0),
            int(flagged or 0),
            int(high_risk or 0),
            int(approved or 0),
            int(rejected or 0),
        )

    @staticmethod
    def _application_snapshot(row: AccessApplication) -> ApplicationSnapshot:
        return ApplicationSnapshot(
            row.id,
            row.guild_id,
            row.discord_user_id,
            row.discord_username_snapshot,
            row.discord_display_name_snapshot,
            row.discovery_source,
            row.referred_by_text,
            tuple(row.interests),
            row.risk_acknowledged,
            row.community_rules_acknowledged,
            row.status,
            row.submitted_at,
            row.reviewed_at,
            row.reviewed_by_user_id,
            row.review_note,
            row.review_channel_id,
            row.review_message_id,
            row.lobby_welcome_message_id,
            row.member_lounge_welcome_message_id,
        )

    @staticmethod
    def _profile_snapshot(row: NewcomerProfile) -> ProfileSnapshot:
        return ProfileSnapshot(
            row.guild_id,
            row.discord_user_id,
            row.discord_username_snapshot,
            row.discord_display_name_snapshot,
            row.first_joined_at,
            row.last_joined_at,
            row.join_count,
            row.approved_at,
            row.role_sync_status,
        )

    @staticmethod
    def _audit(
        session: object,
        *,
        guild_id: int,
        actor_user_id: int,
        action: str,
        entity_type: str,
        entity_id: str,
        interaction_id: int | None = None,
        before: dict[str, object] | None = None,
        after: dict[str, object] | None = None,
    ) -> None:
        session.add(
            AuditLog(
                guild_id=guild_id,
                actor_user_id=actor_user_id,
                action_type=action,
                entity_type=entity_type,
                entity_id=entity_id,
                before_json=before,
                after_json=after,
                discord_interaction_id=interaction_id,
            )
        )


class NewcomerRiskScanner:
    def __init__(self, database: Database, protected_identity_names: tuple[str, ...]) -> None:
        self.database = database
        self.protected_identity_names = tuple(
            name.strip() for name in protected_identity_names if name.strip()
        )

    @classmethod
    def load(cls, database: Database, path: Path) -> NewcomerRiskScanner:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        names = payload.get("protected_identity_names", ())
        if not isinstance(names, list) or not all(isinstance(item, str) for item in names):
            raise ValueError("protected_identity_names must be a list of strings")
        return cls(database, tuple(names))

    async def scan(
        self,
        guild_id: int,
        user_id: int,
        *,
        username: str,
        display_name: str,
        account_created_at: datetime,
        application_id: uuid.UUID | None = None,
        now: datetime | None = None,
    ) -> RiskScanResult:
        checked_at = _aware(now or utc_now())
        age = checked_at - _aware(account_created_at)
        expected: dict[str, tuple[str, str]] = {}
        if age < timedelta(days=7):
            expected["VERY_NEW_ACCOUNT"] = (
                "HIGH",
                f"Discord 账户创建于 {max(age.days, 0)} 天前。",
            )
        elif age < timedelta(days=30):
            expected["NEW_ACCOUNT"] = (
                "MEDIUM",
                f"Discord 账户创建于 {max(age.days, 0)} 天前。",
            )
        async with self.database.session() as session:
            application_rows = (
                await session.execute(
                    select(AccessApplication.id, AccessApplication.status).where(
                        AccessApplication.guild_id == guild_id,
                        AccessApplication.discord_user_id == user_id,
                    )
                )
            ).all()
            statuses = {row.status for row in application_rows}
            application_entity_ids = {str(row.id) for row in application_rows}
            previously_flagged = False
            if application_entity_ids:
                previously_flagged = (
                    await session.scalar(
                        select(AuditLog.id).where(
                            AuditLog.guild_id == guild_id,
                            AuditLog.action_type == "APPLICATION_FLAGGED",
                            AuditLog.entity_type == "access_application",
                            AuditLog.entity_id.in_(application_entity_ids),
                        )
                    )
                ) is not None
            profile = await session.get(NewcomerProfile, (guild_id, user_id))
            trial_id = await session.scalar(
                select(MembershipTrial.id).where(
                    MembershipTrial.discord_user_id == user_id,
                    MembershipTrial.trial_type == EntitlementType.FREE_TRIAL.value,
                )
            )
            if AccessApplicationStatus.REJECTED.value in statuses:
                expected["PREVIOUS_REJECTION"] = ("MEDIUM", "该用户曾有加入申请被拒绝。")
            if AccessApplicationStatus.FLAGGED.value in statuses or previously_flagged:
                expected["PREVIOUS_FLAG"] = ("MEDIUM", "该用户曾有加入申请被标记。")
            if trial_id is not None:
                expected["TRIAL_ALREADY_USED"] = (
                    "LOW",
                    "已有永久免费体验记录，不能再次领取。",
                )
            if profile is not None and profile.join_count > 1 and profile.approved_at is None:
                expected["REJOIN_WITHOUT_APPROVAL"] = (
                    "LOW",
                    f"该用户未获批准，已加入 AXIS {profile.join_count} 次。",
                )
            matched = self.protected_identity_match(username, display_name)
            if matched is not None:
                expected["POSSIBLE_IMPERSONATION"] = (
                    "HIGH",
                    f"用户名或显示名称与受保护身份相似：{matched}",
                )

            current = {
                row.risk_code: row
                for row in (
                    await session.scalars(
                        select(NewcomerRiskFlag)
                        .where(
                            NewcomerRiskFlag.guild_id == guild_id,
                            NewcomerRiskFlag.discord_user_id == user_id,
                        )
                        .with_for_update()
                    )
                ).all()
            }
            created: list[str] = []
            resolved: list[str] = []
            for code, (severity, details) in expected.items():
                row = current.get(code)
                if row is None:
                    row = NewcomerRiskFlag(
                        guild_id=guild_id,
                        discord_user_id=user_id,
                        application_id=application_id,
                        risk_code=code,
                        severity=severity,
                        details=details,
                        first_seen_at=checked_at,
                        last_seen_at=checked_at,
                        occurrence_count=1,
                    )
                    session.add(row)
                    await session.flush()
                    created.append(code)
                    NewcomerAccessService._audit(
                        session,
                        guild_id=guild_id,
                        actor_user_id=user_id,
                        action="RISK_FLAG_CREATED",
                        entity_type="newcomer_risk_flag",
                        entity_id=str(row.id),
                        after={"risk_code": code, "severity": severity},
                    )
                else:
                    row.application_id = application_id or row.application_id
                    row.severity = severity
                    row.details = details
                    row.last_seen_at = checked_at
                    row.occurrence_count += 1
                    row.resolved_at = None
            for code, row in current.items():
                if code not in expected and row.resolved_at is None:
                    row.resolved_at = checked_at
                    resolved.append(code)
                    NewcomerAccessService._audit(
                        session,
                        guild_id=guild_id,
                        actor_user_id=user_id,
                        action="RISK_FLAG_RESOLVED",
                        entity_type="newcomer_risk_flag",
                        entity_id=str(row.id),
                        before={"risk_code": code},
                        after={"resolved_at": checked_at.isoformat()},
                    )
            await session.commit()
            rows = (
                await session.scalars(
                    select(NewcomerRiskFlag)
                    .where(
                        NewcomerRiskFlag.guild_id == guild_id,
                        NewcomerRiskFlag.discord_user_id == user_id,
                        NewcomerRiskFlag.resolved_at.is_(None),
                    )
                    .order_by(NewcomerRiskFlag.severity.desc(), NewcomerRiskFlag.risk_code)
                )
            ).all()
            return RiskScanResult(
                tuple(self._snapshot(row) for row in rows),
                tuple(created),
                tuple(resolved),
            )

    def protected_identity_match(self, *names: str) -> str | None:
        protected = {self._skeleton(item): item for item in self.protected_identity_names}
        for name in names:
            match = protected.get(self._skeleton(name))
            if match is not None:
                return match
        return None

    @staticmethod
    def _skeleton(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value).upper()
        collapsed = "".join(character for character in normalized if character.isalnum())
        collapsed = collapsed.translate(str.maketrans({"0": "O", "1": "I", "4": "A", "5": "S"}))
        if len(collapsed) >= 4 and collapsed.startswith("AX") and collapsed[2] == "L":
            collapsed = collapsed[:2] + "I" + collapsed[3:]
        return collapsed

    @staticmethod
    def _snapshot(row: NewcomerRiskFlag) -> RiskFlagSnapshot:
        return RiskFlagSnapshot(
            row.id,
            row.discord_user_id,
            row.application_id,
            row.risk_code,
            row.severity,
            row.details,
            row.occurrence_count,
            row.first_seen_at,
            row.last_seen_at,
            row.resolved_at,
        )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
