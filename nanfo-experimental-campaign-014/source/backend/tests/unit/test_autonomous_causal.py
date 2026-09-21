"""Native acquisition reconstruction, no privileged instrumentation in tests."""

import copy
import json
import uuid
from datetime import UTC, datetime

import pytest

from app.modules.autonomy.causal_frames import CausalConfig, safety_frame
from app.modules.autonomy.schemas import Observation, contract_digest
from emulation.autonomous_causal import acquire_window, provision_rules, validate_capture


def configuration():
    return CausalConfig(version="nanfo.frr-causal-instrument/v1", network_id=uuid.uuid4(), workspace_id=uuid.uuid4(),
        run_id="run-1", runtime_binding_sha256="b" * 64, guarantee_sha256="c" * 64, configuration_sha256="d" * 64,
        window_seconds=.01, clock_error_seconds=.1, max_read_span_seconds=1.,
        egresses=[dict(egress_id="egress1", node="access1", interface="access1-eth1", source="s", destination="t",
                      leaf_handle="10:", capacity_bytes_per_second=1000., measurement_error_bytes=0.)],
        demands=[dict(demand_id="foreground", source="s", destination="t", source_ipv4="10.0.0.1",
                      destination_ipv4="10.0.0.2", ip_protocol=17,
                      enforced_lower_bytes_per_second=0., enforced_upper_bytes_per_second=2000.)])


class Instrument:
    def __init__(self, config):
        self.config, self.index = config, 0

    def routePath(self, source, destination):
        return {"nodes": [source, "access1", "dist1", "access2", destination]}

    def command(self, node, args):
        if args[0] == "nft":
            values = copy.deepcopy(provision_rules(self.config)[node])
            rows = [v["add"] for v in values["nftables"]]
            for value in rows:
                if "counter" in value:
                    value["counter"].update(packets=self.index, bytes=100 * self.index if value["counter"]["name"].endswith("foreground") else 0)
            return json.dumps({"nftables": rows})
        if "class" in args:
            return json.dumps([{"kind": "htb", "handle": "5:1", "options": {"rate": 1000}}])
        result = [{"kind": "netem", "handle": "10:", "parent": "5:1", "backlog": 10 * self.index, "bytes": 90 * self.index, "drops": 0}]
        self.index += 1
        return json.dumps(result)


def capture():
    config = configuration()
    result = acquire_window(Instrument(config.model_dump(mode="json")), config.model_dump(mode="json"))
    return config, result


def test_acquisition_raw_bytes_and_native_reconstruction_not_threshold_calibration():
    config, result = capture()
    assert result["measurement_complete"] and not result["guaranteed_bounds"]
    assert result["after"]["queues"][0]["queue_bytes"] == 10
    validate_capture(result, config.model_dump(mode="json"))


@pytest.mark.parametrize("mutation", ["native", "counter", "rule", "unknown", "drops", "clock", "capacity"])
def test_native_tampering_unknown_drop_and_clock_fail_closed(mutation):
    config, result = capture()
    end = result["after"]
    if mutation == "native":
        end["queues"][0]["raw_qdiscs"][0]["backlog"] += 1
    elif mutation == "counter":
        end["queues"][0]["demand_arrivals_bytes"]["foreground"] += 1
    elif mutation == "rule":
        for row in end["raw_nftables"]["access1"]["nftables"]:
            if "rule" in row:
                row["rule"]["expr"] = []
                break
    elif mutation == "unknown":
        for row in end["raw_nftables"]["access1"]["nftables"]:
            if row.get("counter", {}).get("name", "").endswith("unknown"):
                row["counter"]["bytes"] = 1
        end["queues"][0]["demand_arrivals_bytes"]["unknown"] = 1
    elif mutation == "drops":
        end["queues"][0]["drop_packets"] = 1
        end["queues"][0]["raw_qdiscs"][0]["drops"] = 1
    elif mutation == "capacity":
        end["queues"][0]["raw_classes"][0]["options"]["rate"] = 100
    else:
        end["finished_monotonic"] += 5
    with pytest.raises(ValueError):
        validate_capture(result, config.model_dump(mode="json"))


def test_safety_frame_requires_reviewed_enforced_envelope_and_exact_observer_alignment():
    config, result = capture()
    # Align fixture at actual representable UTC microsecond boundary, not a rate fit.
    observed = datetime.fromtimestamp(result["after"]["finished_unix"], UTC)
    result["after"]["finished_unix"] = observed.timestamp()
    result["after"]["queues"][0]["read_finished"] = min(result["after"]["queues"][0]["read_finished"], observed.timestamp())
    observation = Observation(network_id=config.network_id, workspace_id=config.workspace_id, provider_id="test",
        contract="test.measured.v1", observed_at=observed, collected_at=observed, age_seconds=0,
        fresh=True, compatible=True, evidence=["test:actual-endpoint"])
    result.update(observation_sha256=contract_digest(observation), instrument_sha256=contract_digest(config),
                  runtime_binding_sha256=config.runtime_binding_sha256, run_id=config.run_id)
    frame = safety_frame(config, result, observation, sequence=1, accepted_guarantees={config.guarantee_sha256},
                         accepted_instruments={contract_digest(config)})
    assert frame.demands[0].arrival_upper_bytes_per_second == 2000  # reviewed envelope, not100/dt
    assert frame.queues[0].queue_bytes == 10
    with pytest.raises(ValueError):
        safety_frame(config, result, observation, sequence=1, accepted_guarantees=set(),
                     accepted_instruments={contract_digest(config)})
