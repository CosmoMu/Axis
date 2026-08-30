#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import String, cast, func, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings  # noqa: E402
from app.db.models import (  # noqa: E402
    AnalysisDraft,
    AnalysisIndicator,
    AnalysisPredictionPoint,
    AnalysisScenario,
    MentorAnalysis,
)
from app.db.session import Database  # noqa: E402


async def verify() -> int:
    settings = Settings.load(PROJECT_ROOT)
    database = Database(settings.require_database_url())
    try:
        async with database.session() as session:
            draft_total = await session.scalar(select(func.count()).select_from(AnalysisDraft))
            draft_layered = await session.scalar(
                select(func.count())
                .select_from(AnalysisDraft)
                .where(cast(AnalysisDraft.normalized_mentor_json, String) != "{}")
            )
            archive_total = await session.scalar(
                select(func.count()).select_from(MentorAnalysis)
            )
            archive_layered = await session.scalar(
                select(func.count())
                .select_from(MentorAnalysis)
                .where(
                    cast(MentorAnalysis.raw_source_json, String) != "{}",
                    cast(MentorAnalysis.final_fused_json, String) != "{}",
                )
            )
            indicator_count = await session.scalar(
                select(func.count()).select_from(AnalysisIndicator)
            )
            scenario_count = await session.scalar(
                select(func.count()).select_from(AnalysisScenario)
            )
            path_count = await session.scalar(
                select(func.count()).select_from(AnalysisPredictionPoint)
            )
        print(
            "analysis_fusion="
            f"draft_layers:{draft_layered}/{draft_total},"
            f"archive_layers:{archive_layered}/{archive_total},"
            f"indicators:{indicator_count},scenarios:{scenario_count},path_points:{path_count}"
        )
        return 0 if draft_layered == draft_total and archive_layered == archive_total else 2
    finally:
        await database.dispose()


def main() -> int:
    try:
        return asyncio.run(verify())
    except Exception as exc:
        print(
            "Analysis fusion verification failed; connection details were omitted. "
            f"error_type={type(exc).__name__}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
