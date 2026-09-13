#!/usr/bin/env python3
"""Secret-safe database/config verifier for AXIS Multi-Agent Research."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import inspect, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings  # noqa: E402
from app.db.session import Database  # noqa: E402
from app.domain.enums import LlmWorkload  # noqa: E402
from app.integrations.model_router import ModelRouter  # noqa: E402
from app.market_intelligence.research_engine.policy import ResearchPolicy  # noqa: E402

REQUIRED_TABLES = {
    "research_runs",
    "research_agent_outputs",
    "research_outcomes",
    "research_reflections",
}
RESEARCH_WORKLOADS = {
    LlmWorkload.RESEARCH_BULL,
    LlmWorkload.RESEARCH_BEAR,
    LlmWorkload.RESEARCH_MANAGER,
    LlmWorkload.RESEARCH_RISK_AGGRESSIVE,
    LlmWorkload.RESEARCH_RISK_NEUTRAL,
    LlmWorkload.RESEARCH_RISK_CONSERVATIVE,
    LlmWorkload.RESEARCH_SYNTHESIS,
    LlmWorkload.RESEARCH_REFLECTION,
}


async def run() -> dict[str, object]:
    settings = Settings.load(PROJECT_ROOT)
    settings.assert_research_safety()
    policy = ResearchPolicy.load(
        settings.research_policy_path, version_override=settings.research_policy_version
    )
    router = ModelRouter.load(settings.llm_routing_path)
    routes = {workload.value: router.resolve(workload).model for workload in RESEARCH_WORKLOADS}
    database = Database(settings.require_database_url())
    try:
        async with database.engine.connect() as connection:
            tables = await connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))
            revision = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
    finally:
        await database.dispose()
    missing = sorted(REQUIRED_TABLES - tables)
    if missing:
        raise RuntimeError("RESEARCH_DATABASE_TABLES_MISSING")
    return {
        "status": "PASS",
        "mode": settings.research_mode,
        "enabled": settings.research_enabled,
        "policy_version": policy.version,
        "database_revision": revision,
        "tables": sorted(REQUIRED_TABLES),
        "llm_workloads": sorted(routes),
        "stock_reuse": settings.stock_analyst_enabled,
        "gex_reuse": settings.gex_explorer_enabled,
        "member_lounge_launch": False,
        "broker_execution": False,
    }


def main() -> int:
    try:
        print(json.dumps(asyncio.run(run()), ensure_ascii=False, indent=2))
    except Exception as exc:
        print(
            json.dumps(
                {"status": "FAIL", "error_type": type(exc).__name__},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
