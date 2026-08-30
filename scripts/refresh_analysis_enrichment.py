#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings  # noqa: E402
from app.db.models import AnalysisDraft, SourceMessage  # noqa: E402
from app.db.session import Database  # noqa: E402
from app.domain.enums import AnalysisDraftStatus, LlmWorkload, SourceKind  # noqa: E402
from app.integrations.model_router import ModelRouter  # noqa: E402
from app.integrations.openai_analysis_parser import (  # noqa: E402
    OpenAIAnalysisParser,
    load_analysis_prompt,
    load_analysis_schema,
)
from app.market_intelligence.stock_analyst import AxisStockAnalystService  # noqa: E402
from app.services.analysis_pipeline import AnalysisPipelineService  # noqa: E402
from app.services.attachment_storage import LocalAttachmentStore  # noqa: E402


async def refresh(message_id: int, settings_root: Path) -> int:
    settings = Settings.load(settings_root)
    database = Database(settings.require_database_url())
    parsers: list[OpenAIAnalysisParser] = []
    try:
        async with database.session() as session:
            row = (
                await session.execute(
                    select(SourceMessage, AnalysisDraft)
                    .join(AnalysisDraft, AnalysisDraft.source_message_id == SourceMessage.id)
                    .where(
                        SourceMessage.guild_id == settings.discord_guild_id,
                        SourceMessage.discord_message_id == message_id,
                        SourceMessage.source_kind == SourceKind.ANALYSIS.value,
                    )
                )
            ).one_or_none()
        if row is None:
            print("Analysis refresh stopped: draft was not found.", file=sys.stderr)
            return 2
        source, draft = row
        if draft.status not in {
            AnalysisDraftStatus.PENDING_REVIEW.value,
            AnalysisDraftStatus.PARSE_FAILED.value,
        }:
            print("Analysis refresh stopped: draft is immutable.", file=sys.stderr)
            return 2
        if not settings.axis_stock_analyst_enabled:
            print("Analysis refresh stopped: AXIS Stock Analyst is disabled.", file=sys.stderr)
            return 2

        router = ModelRouter.load(
            settings.llm_routing_path,
            model_overrides={
                LlmWorkload.SIGNAL_PARSE: settings.llm_signal_model_override,
                LlmWorkload.SIGNAL_REPAIR: settings.llm_signal_repair_model_override,
                LlmWorkload.ANALYSIS_PARSE: settings.llm_analysis_model_override,
                LlmWorkload.ANALYSIS_REWRITE: settings.llm_analysis_rewrite_model_override,
            },
            default_model_override=settings.llm_default_model_override,
            timeout_seconds_override=settings.llm_timeout_seconds,
            max_retries_override=settings.llm_max_retries,
        )
        parse_route = router.resolve(LlmWorkload.ANALYSIS_PARSE)
        rewrite_route = router.resolve(LlmWorkload.ANALYSIS_REWRITE)
        if parse_route.structured_output is None or rewrite_route.structured_output is None:
            print("Analysis refresh stopped: structured schema is missing.", file=sys.stderr)
            return 2
        schema = load_analysis_schema(parse_route.structured_output)
        prompt = load_analysis_prompt(settings.llm_analysis_prompt_path)
        parsers = [
            OpenAIAnalysisParser(
                api_key=settings.require_openai_api_key(),
                route=parse_route,
                schema=schema,
                prompt=prompt,
            ),
            OpenAIAnalysisParser(
                api_key=settings.require_openai_api_key(),
                route=rewrite_route,
                schema=load_analysis_schema(rewrite_route.structured_output),
                prompt=prompt,
            ),
        ]
        service = AnalysisPipelineService(
            database,
            LocalAttachmentStore(
                settings.attachment_storage_path,
                max_bytes=settings.max_attachment_bytes,
            ),
            parsers[0],
            parsers[1],
            schema,
            AxisStockAnalystService(
                host=settings.moomoo_host,
                port=settings.moomoo_port,
            ),
        )
        updated = await service.rewrite(
            draft.id,
            "重新识别原始观点及图片是否画有明确的未来预测路径；保留原观点，并合并当前 "
            "AXIS Stock Analyst 数据，并单独保留为什么现在关注。",
            actor_user_id=source.submitted_by,
            interaction_id=None,
        )
        print(f"message_id={message_id}")
        print(f"draft_code={updated.draft_code}")
        print(f"draft_status={updated.status}")
        print(f"revision={updated.revision}")
        print(f"chart_source={updated.chart_source or 'NONE'}")
        print(f"review_message_id={updated.review_message_id}")
        return 0
    finally:
        for parser in parsers:
            await parser.client.close()
        await database.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh one editable Analysis with current AXIS Stock Analyst context."
    )
    parser.add_argument("--message-id", type=int, required=True)
    parser.add_argument("--settings-root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()
    try:
        return asyncio.run(refresh(args.message_id, args.settings_root.resolve()))
    except Exception as exc:
        print(
            "Analysis refresh failed; sensitive details were omitted. "
            f"error_type={type(exc).__name__}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
