#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings  # noqa: E402
from app.db.session import Database  # noqa: E402

EXPECTED_REVISION = "20260831_0025"

COUNTED_TABLES = (
    "input_code_counters",
    "source_messages",
    "trade_drafts",
    "trades",
    "mentors",
    "memberships",
    "membership_sessions",
    "membership_prices",
    "membership_acknowledgements",
    "membership_entitlements",
    "membership_trials",
    "payment_events",
    "payment_webhook_events",
    "system_alerts",
    "trade_events",
    "trade_publications",
    "analysis_drafts",
    "mentor_analyses",
    "analysis_publications",
    "market_quote_snapshots",
    "daily_summary_publications",
    "short_term_tracking",
    "short_term_tracking_events",
    "short_term_daily_snapshots",
    "daily_results_publications",
    "daily_results_reviews",
    "daily_results_items",
)
SAFE_FEATURES = (
    "FEATURE_ANALYSIS_ENABLED",
    "FEATURE_AXIS_STOCK_ANALYST_ENABLED",
    "FEATURE_DAILY_SUMMARY_ENABLED",
    "FEATURE_SHORT_TERM_TRACKING_ENABLED",
    "FEATURE_LAB_ENABLED",
    "FEATURE_MODEL_AB_ENABLED",
    "FEATURE_MOOMOO_ENABLED",
    "RESULTS_REVIEW_ENABLED",
)


def _safe_feature(name: str) -> str:
    value = os.getenv(name, "false").strip().lower()
    return value if value in {"true", "false"} else "invalid"


async def verify() -> None:
    settings = Settings.load(PROJECT_ROOT)
    database = Database(settings.require_database_url())
    try:
        async with database.session() as session:
            revision = (
                await session.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            if revision != EXPECTED_REVISION:
                raise RuntimeError("DATABASE_REVISION_MISMATCH")
            trial_columns = {
                row[0]
                for row in (
                    await session.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_name='membership_trials'"
                        )
                    )
                ).all()
            }
            required_trial_columns = {
                "duration_unit",
                "duration_amount",
                "calendar_days_granted",
                "started_at",
                "expires_at",
            }
            if not required_trial_columns <= trial_columns:
                raise RuntimeError("MEMBERSHIP_TRIAL_SCHEMA_MISMATCH")
            counts = {}
            for table in COUNTED_TABLES:
                exists = (
                    await session.execute(
                        text("SELECT to_regclass(:table_name)"),
                        {"table_name": table},
                    )
                ).scalar_one()
                if exists is None:
                    counts[table] = "NOT_MIGRATED"
                    continue
                result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
                counts[table] = result.scalar_one()
        print(f"revision={revision}")
        print("counts=" + ",".join(f"{name}:{count}" for name, count in counts.items()))
        print(
            "feature_flags=" + ",".join(f"{name}:{_safe_feature(name)}" for name in SAFE_FEATURES)
        )
    finally:
        await database.dispose()


def main() -> int:
    try:
        asyncio.run(verify())
    except Exception as exc:
        print(
            "AXIS database verification failed; connection details were omitted. "
            f"error_type={type(exc).__name__}",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
