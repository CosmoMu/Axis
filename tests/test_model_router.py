from pathlib import Path

import pytest

from app.domain.enums import LlmWorkload
from app.integrations.model_router import ModelRouter, ModelRoutingError

ROOT = Path(__file__).resolve().parents[1]


def test_router_resolves_all_workloads_without_one_global_business_model() -> None:
    router = ModelRouter.load(ROOT / "config" / "model_routing.yaml")

    signal = router.resolve(LlmWorkload.SIGNAL_PARSE)
    analysis = router.resolve(LlmWorkload.ANALYSIS_PARSE)

    assert signal.model == "gpt-5.6-terra"
    assert signal.reasoning == "low"
    assert signal.prompt_version == "axis-trade-parse-v3"
    assert signal.schema_version == "axis-trade-v2"
    assert signal.structured_output == (ROOT / "config" / "llm_trade_schema.json").resolve()
    assert analysis.model == "gpt-5.6-terra"
    assert analysis.workload is LlmWorkload.ANALYSIS_PARSE


def test_analysis_override_does_not_change_signal_route() -> None:
    router = ModelRouter.load(
        ROOT / "config" / "model_routing.yaml",
        model_overrides={LlmWorkload.ANALYSIS_PARSE: "gpt-5.6-sol"},
    )

    assert router.resolve(LlmWorkload.ANALYSIS_PARSE).model == "gpt-5.6-sol"
    assert router.resolve(LlmWorkload.SIGNAL_PARSE).model == "gpt-5.6-terra"


def test_unknown_workload_is_rejected() -> None:
    router = ModelRouter.load(ROOT / "config" / "model_routing.yaml")

    with pytest.raises(ModelRoutingError):
        router.resolve("LAB_GENERATE")


def test_config_reference_files_match_runtime_config() -> None:
    pairs = (
        ("discord_blueprint.yaml",),
        ("model_routing.yaml",),
        ("llm_trade_schema.json",),
        ("llm_analysis_schema.json",),
        ("llm_analysis_prompt.txt",),
    )
    for (filename,) in pairs:
        assert (ROOT / "docs" / "config-reference" / filename).read_bytes() == (
            ROOT / "config" / filename
        ).read_bytes()
