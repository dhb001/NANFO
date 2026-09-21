"""Deterministic assumptions/sensitivity and CLI contract, no physical controls."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.modules.network.energy_estimate import EnergyScenario, estimate_energy


def scenario():
    return {
        "duration_hours": 2,
        "nodes": ["a", "b", "c"],
        "links": [
            {"link_id": key, "source": source, "target": target, "active_watts": 10, "idle_watts": 2}
            for key, source, target in [("ab", "a", "b"), ("bc", "b", "c"), ("ac", "a", "c")]
        ],
        "candidate_idle_link_ids": ["ac"],
    }


def test_estimate_is_pure_and_explicitly_model_only():
    data = scenario()
    validated = EnergyScenario.model_validate(data)
    result = estimate_energy(validated)
    assert validated.model_dump() == data
    assert result == estimate_energy(validated)
    assert result.baseline_energy_wh == 60
    assert result.candidate_energy_wh == 44
    assert result.estimated_savings_wh == 16
    assert result.model_only is True
    assert result.guaranteed_savings is result.physical_control is False
    assert result.controls_status == "unsupported"
    assert result.power_control_acceptance == "blocked"
    assert result.connectivity_status == "modeled_connected"


def test_assumptions_sensitivity_and_negative_savings_not_hidden():
    data = scenario()
    data["duration_hours"] = 4
    assert estimate_energy(EnergyScenario.model_validate(data)).estimated_savings_wh == 32
    data["links"][2]["idle_watts"] = 12
    assert estimate_energy(EnergyScenario.model_validate(data)).estimated_savings_wh == -8
    data["candidate_idle_link_ids"] = []
    assert estimate_energy(EnergyScenario.model_validate(data)).estimated_savings_wh == 0


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), "10", True, 1_000_001])
@pytest.mark.parametrize("field", ["active_watts", "idle_watts"])
def test_invalid_wattage_is_rejected(field, value):
    data = scenario()
    data["links"][0][field] = value
    with pytest.raises(ValidationError):
        EnergyScenario.model_validate(data)


@pytest.mark.parametrize("value", [-1, 0, float("nan"), float("inf"), "2", True, 8785])
def test_invalid_duration_is_rejected(value):
    data = scenario()
    data["duration_hours"] = value
    with pytest.raises(ValidationError):
        EnergyScenario.model_validate(data)


@pytest.mark.parametrize("field", ["active_watts", "idle_watts"])
def test_no_inferred_wattage(field):
    data = scenario()
    del data["links"][0][field]
    with pytest.raises(ValidationError):
        EnergyScenario.model_validate(data)


@pytest.mark.parametrize("changes", [
    {"candidate_idle_link_ids": ["ab", "ac"]},
    {"candidate_idle_link_ids": ["unknown"]},
    {"candidate_idle_link_ids": ["ab", "ab"]},
    {"nodes": ["a", "b", "c", "d"]},
    {"nodes": ["a", "a", "c"]},
    {"nodes": []}, {"nodes": ["a", "b"]},
    {"physical_control": True},
])
def test_graph_and_plan_validation(changes):
    data = scenario()
    data.update(changes)
    with pytest.raises(ValidationError):
        EnergyScenario.model_validate(data)


def test_duplicate_links_and_self_edges_rejected():
    data = scenario()
    data["links"][1]["link_id"] = "ab"
    with pytest.raises(ValidationError):
        EnergyScenario.model_validate(data)
    data = scenario()
    data["links"][0]["target"] = "a"
    with pytest.raises(ValidationError):
        EnergyScenario.model_validate(data)


def test_public_function_revalidates_mutated_input():
    data = EnergyScenario.model_validate(scenario())
    data.candidate_idle_link_ids.append("ab")
    with pytest.raises(ValidationError):
        estimate_energy(data)


@pytest.mark.parametrize("raw,code", [(json.dumps(scenario()), 0), ('{"duration_hours": -1}', 2),
                                       ("not-json", 2), ("x" * 1_048_577, 2)],
                         ids=["valid", "invalid", "malformed", "oversized"])
def test_stdin_cli(raw, code):
    script = Path(__file__).resolve().parents[2] / "scripts" / "estimate_energy.py"
    process = subprocess.run([sys.executable, str(script)], input=raw, text=True, capture_output=True, timeout=10)
    assert process.returncode == code
    payload = json.loads(process.stdout if code == 0 else process.stderr)
    assert payload["model_only"] is True
    if code == 0:
        assert payload["physical_control"] is False
        assert payload["estimated_savings_wh"] == 16
        assert process.stderr == ""
    else:
        assert process.stdout == ""
