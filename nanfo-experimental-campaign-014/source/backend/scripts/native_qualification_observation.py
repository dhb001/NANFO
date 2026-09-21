"""Passive native causal observation construction on the SAME raw capture.

No new timestamps, rereading of a lab, publication, freshness claim, model vector,
trust installation or registration. The owner publishes only after its existing
identity/freshness checks. Never attach this clock to an independent v4 IPC frame.
"""

from app.modules.autonomy.causal_frames import CausalConfig
from app.modules.autonomy.schemas import Observation, contract_digest
from emulation.native_qualification_causal import validate_ns_capture
from emulation.native_qualification_clock import causal_clock_binding, observation_datetime


def passive_causal_observation(config, raw_capture, *, collected_at):
    config = CausalConfig.model_validate(config)
    if config.version != "nanfo.frr-causal-instrument/v2":
        raise ValueError("native_passive_v2_required")
    validate_ns_capture(raw_capture, config.model_dump(mode="json"))
    binding = causal_clock_binding(raw_capture)
    observed_at = observation_datetime(binding)
    age = (collected_at - observed_at).total_seconds()
    if age < 0:
        raise ValueError("native_collection_precedes_observation")
    observation = Observation(network_id=config.network_id, workspace_id=config.workspace_id,
        provider_id="native-causal-passive-v2", contract="nanfo.native-causal-observation/v2",
        observed_at=observed_at, collected_at=collected_at, age_seconds=age,
        fresh=False, compatible=False, evidence=["native-capture:" + binding["raw_capture_sha256"]])
    return observation, {
        "version": "nanfo.frr-causal-envelope/v2", "raw_capture": raw_capture,
        "clock_binding": binding, "observation_sha256": contract_digest(observation),
        "instrument_sha256": contract_digest(config), "runtime_binding_sha256": config.runtime_binding_sha256,
        "run_id": config.run_id,
    }
