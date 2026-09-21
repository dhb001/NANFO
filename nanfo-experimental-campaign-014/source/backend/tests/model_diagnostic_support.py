"""Disposable operator registry of the actual ADR014 incumbent, never fake vectors."""

import hashlib
import json
from pathlib import Path
import zipfile

CHECKPOINT_HASH = "5b8818af655ec8efce5d3bc3def27db599f3e0df379a0ae263dcefb5f72a80a5"
HISTORY_HASH = "1ed5856374244fc1a547b05043f5c7f05d5a2da89a285fd27ec09186ba3123b7"


def provision_registry(directory, network_id):
    ai = Path(__file__).resolve().parents[2] / "ai-engine"
    checkpoint = ai / "artifacts/adr014-001/train-06/checkpoint.ptz"
    assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == CHECKPOINT_HASH
    with zipfile.ZipFile(checkpoint) as archive:
        manifest = json.loads(archive.read("manifest.json"))

    def artifact(relative):
        content = (ai / relative).read_bytes()
        return {"path": relative, "sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content)}

    history = artifact("artifacts/adr014-001/validation-06/last-history.json")
    assert history["sha256"] == HISTORY_HASH
    registry = {"version": 1, "models": [{
        "model_id": "adr014-incumbent", "checkpoint_id": "train-06",
        "network_ids": [str(network_id)],
        "checkpoint": artifact("artifacts/adr014-001/train-06/checkpoint.ptz"),
        "source_directory": "artifacts/adr014-001/source",
        "source_sha256": manifest["client_source_files"],
        "histories": {"validation-06": {"artifact": history, "network_ids": [str(network_id)]}},
        "benchmark": {
            "status": "qualified_scoped_benchmark",
            "scope": "ADR014 reserved 12 seeds, balanced stationary 2/20 Mbps impairment versus frozen nominal-cost OSPF; gain from avoiding the impaired nominal route.",
            "limitations": ["Not capacity-aware OSPF or arbitrary-network superiority.",
                             "ICMP RTT; one shuffled session order; not calibrated production safety.",
                             "Historical measured inference, no compatible live observer or execution authorization."],
            "evidence": artifact("artifacts/adr014-holdout-001/test-report.json"),
        },
    }]}
    path = directory / "registry.json"
    content = json.dumps(registry, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(content)
    path.chmod(0o600)
    env = {"NANFO_MODEL_REGISTRY": str(path), "NANFO_MODEL_REGISTRY_SHA256": hashlib.sha256(content).hexdigest(),
           "NANFO_MODEL_ROOT": str(ai), "NANFO_MODEL_PYTHON": str(ai / ".venv/bin/python")}
    return env, registry
