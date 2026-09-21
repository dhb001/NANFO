"""Typed output must retain every hashed field and never disguise malformed models as legacy."""

import copy

import pytest
from pydantic import TypeAdapter, ValidationError

from app.api.v1.simulation import ScenarioValidationState
from app.modules.simulation.schemas import (
    ModeledOutput,
    SimulationTrace,
    UnavailableOutput,
)
from tests.simulation_support import completed, scenario


def test_modeled_output_and_trace_roundtrip_all_fields():
    _, result = completed(scenario())
    assert TypeAdapter(ModeledOutput | UnavailableOutput).validate_python(result).model_dump() == result
    for tick in result["trace"]:
        assert SimulationTrace.model_validate(tick).model_dump() == tick


@pytest.mark.parametrize("mutate", [
    lambda r: r.pop("flows"),
    lambda r: r.update(physical_safety_authorized=True),
    lambda r: r.update(loss_pct=float("nan")),
    lambda r: r["trace"][0]["links"]["ab"]["flows"]["f"].pop("queued_bytes"),
    lambda r: r.update(extra="unapproved"),
])
def test_invalid_modeled_output_cannot_fall_through_legacy_union(mutate):
    result = copy.deepcopy(completed(scenario())[1])
    mutate(result)
    with pytest.raises(ValidationError):
        TypeAdapter(ModeledOutput | UnavailableOutput).validate_python(result)


def test_missing_legacy_metrics_are_null_not_zero():
    assert UnavailableOutput.model_validate({}).model_dump() == {
        "latency_ms": None, "loss_pct": None, "throughput_mbps": None,
    }
    with pytest.raises(ValidationError):
        UnavailableOutput.model_validate({"latency_ms": 0})


def test_handoff_retains_source_and_false_physical_safety():
    value = {"pipeline_stage": "queued", "required_checks": [], "policy_reference": "ADR-017",
             "status": "pending", "queued_at": "now", "requested_by_user_id": "actor",
             "source": "operator_configured_model", "physical_safety_authorized": False}
    result = ScenarioValidationState.model_validate(value).model_dump()
    assert result["source"] == value["source"] and result["physical_safety_authorized"] is False
    with pytest.raises(ValidationError):
        ScenarioValidationState.model_validate({**value, "physical_safety_authorized": True})
