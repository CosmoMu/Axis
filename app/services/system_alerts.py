from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from app.db.models import SystemAlert, utc_now
from app.db.session import Database


@dataclass(frozen=True, slots=True)
class SystemAlertSnapshot:
    id: uuid.UUID
    severity: str
    service: str
    error_type: str
    affected: str | None
    detail: str | None
    first_seen: datetime
    last_seen: datetime
    occurrence_count: int
    resolved_at: datetime | None


@dataclass(frozen=True, slots=True)
class AlertDecision:
    action: str
    alert: SystemAlertSnapshot


class SystemAlertService:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def fingerprint(service: str, error_type: str, affected: str | None) -> str:
        material = "\x1f".join((service.strip(), error_type.strip(), (affected or "").strip()))
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    async def report_failure(
        self,
        guild_id: int,
        *,
        severity: str,
        service: str,
        error_type: str,
        affected: str | None = None,
        detail: str | None = None,
        first_seen: datetime | None = None,
        occurrence_count: int = 1,
    ) -> AlertDecision:
        if severity not in {"WARNING", "ERROR"}:
            raise ValueError("ALERT_SEVERITY_INVALID")
        if occurrence_count < 1:
            raise ValueError("ALERT_OCCURRENCE_INVALID")
        now = utc_now()
        started = first_seen or now
        fingerprint = self.fingerprint(service, error_type, affected)
        async with self.database.session() as session:
            alert = await session.scalar(
                select(SystemAlert)
                .where(
                    SystemAlert.guild_id == guild_id,
                    SystemAlert.fingerprint == fingerprint,
                )
                .with_for_update()
            )
            if alert is None:
                alert = SystemAlert(
                    guild_id=guild_id,
                    fingerprint=fingerprint,
                    severity=severity,
                    service=service[:64],
                    error_type=error_type[:100],
                    affected=affected[:255] if affected else None,
                    detail=detail[:1000] if detail else None,
                    first_seen=started,
                    last_seen=now,
                    occurrence_count=occurrence_count,
                )
                session.add(alert)
                await session.flush()
                action = "ALERT"
            elif alert.resolved_at is not None:
                alert.severity = severity
                alert.detail = detail[:1000] if detail else None
                alert.first_seen = started
                alert.last_seen = now
                alert.occurrence_count = occurrence_count
                alert.resolved_at = None
                alert.last_notified_at = None
                action = "ALERT"
            else:
                alert.severity = severity
                alert.detail = detail[:1000] if detail else alert.detail
                alert.last_seen = now
                alert.occurrence_count += occurrence_count
                action = "ALERT" if alert.last_notified_at is None else "SUPPRESSED"
            await session.commit()
            return AlertDecision(action, self._snapshot(alert))

    async def report_recovery(
        self,
        guild_id: int,
        *,
        service: str,
        error_type: str,
        affected: str | None = None,
    ) -> AlertDecision | None:
        fingerprint = self.fingerprint(service, error_type, affected)
        now = utc_now()
        async with self.database.session() as session:
            alert = await session.scalar(
                select(SystemAlert)
                .where(
                    SystemAlert.guild_id == guild_id,
                    SystemAlert.fingerprint == fingerprint,
                )
                .with_for_update()
            )
            if alert is None or alert.resolved_at is not None:
                return None
            should_notify = alert.last_notified_at is not None
            alert.last_seen = now
            alert.resolved_at = now
            await session.commit()
            return AlertDecision(
                "RECOVERY" if should_notify else "SUPPRESSED",
                self._snapshot(alert),
            )

    async def mark_notified(self, alert_id: uuid.UUID) -> None:
        async with self.database.session() as session:
            alert = await session.get(SystemAlert, alert_id)
            if alert is not None:
                alert.last_notified_at = utc_now()
                await session.commit()

    @staticmethod
    def _snapshot(alert: SystemAlert) -> SystemAlertSnapshot:
        return SystemAlertSnapshot(
            id=alert.id,
            severity=alert.severity,
            service=alert.service,
            error_type=alert.error_type,
            affected=alert.affected,
            detail=alert.detail,
            first_seen=alert.first_seen,
            last_seen=alert.last_seen,
            occurrence_count=alert.occurrence_count,
            resolved_at=alert.resolved_at,
        )
