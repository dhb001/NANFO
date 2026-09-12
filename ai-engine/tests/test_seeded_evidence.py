"""Seed reconstruction regressions, entirely offline and independent of policy quality."""

from copy import deepcopy

import pytest
from conftest import evidenceFixture, producerSchedule

from nanfo_routing.contracts import Request, Response
from nanfo_routing.evidence import validateMeasurement


@pytest.mark.parametrize("mode", ["matched", "ospf"])
@pytest.mark.parametrize("scenario", ["low", "path0", "path1"])
@pytest.mark.parametrize("seed", [0, 1000, 2600, 2998, 3800, 2147483647])
def test_independent_validator_matches_producer_schedule(transport, mode, scenario, seed):
    request = Request(command="reset", seed=seed, scenario=scenario, mode=mode, episode_steps=4)
    schedule = producerSchedule(seed, scenario, 4, mode)
    data = None
    for index, phase in enumerate(schedule):
        if index:
            request = request.model_copy(
                update={
                    "command": "step",
                    "step_index": index,
                    "episode_id": data.episode_id,
                    "action": index % 2,
                }
            )
        data = Response.model_validate(transport.exchange(request)).data
        assert data.evidence["phase"] == phase
        validateMeasurement(data, request)


@pytest.mark.parametrize("mode", ["matched", "ospf"])
@pytest.mark.parametrize("index", [0, 1, 4])
@pytest.mark.parametrize("mutation", ["seed", "foreground", "background", "background_path"])
def test_coherent_seed_or_workload_mutation_rejected(transport, mode, index, mutation):
    request = Request(command="reset", seed=2600, scenario="path0", mode=mode, episode_steps=4)
    raw = transport.exchange(request)
    if index:
        request = request.model_copy(
            update={
                "command": "step",
                "step_index": index,
                "episode_id": raw["data"]["episode_id"],
                "action": 1,
            }
        )
        raw = transport.exchange(request)
    validateMeasurement(Response.model_validate(raw).data, request)
    raw = deepcopy(raw)
    data = raw["data"]
    if mutation == "seed":
        request = request.model_copy(update={"seed": 2998})
        data["seed"] = 2998
    elif mutation == "background_path":
        data["evidence"]["phase"]["background_path"] = 1
    else:
        observation = data["observation"]
        if mutation == "foreground":
            observation["offered_mbps"] += 0.001
            observation["actual_offered_mbps"] = observation["offered_mbps"]
        else:
            observation["background_mbps"] += 0.001
        # Rebuild phase, sender/receiver totals, actual rates, goodput and deficit
        # consistently, rather than relying on another aggregate gate to catch it.
        data["evidence"] = evidenceFixture(observation, request)
    with pytest.raises(ValueError, match="reconstructed seeded stationary"):
        validateMeasurement(Response.model_validate(raw).data, request)
