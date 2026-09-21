"""Private provider fixtures. Historical bytes never become fresh measured evidence."""

import hashlib
import json
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.modules.autonomy.live_settings import LiveSettings
from app.modules.autonomy.registry import LiveRegistry
from scripts.frozen_model_diagnostic import canonical_hash

ROOT = Path(__file__).resolve().parents[2] / "ai-engine"
CHECKPOINT = "artifacts/adr014-001/train-06/checkpoint.ptz"
HISTORY = "artifacts/adr014-001/validation-06/last-history.json"
BENCHMARK = "artifacts/adr014-holdout-001"


def provision(tmp_path, *, snapshot=False):
    def ref(path):
        content = (ROOT / path).read_bytes()
        return dict(path=path, sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content))

    with zipfile.ZipFile(ROOT / CHECKPOINT) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    plan = json.loads((ROOT / BENCHMARK / "plan.json").read_bytes())
    now = datetime.now(UTC)
    network, workspace = uuid.uuid4(), uuid.uuid4()
    observations = tmp_path / "observations"
    observations.mkdir(mode=0o700)
    document = dict(version=1, model_id="adr014-incumbent", checkpoint=ref(CHECKPOINT),
        source_directory="artifacts/adr014-001/source", source_sha256=manifest["client_source_files"],
        contract_sha256=manifest["contract_hash"], spec_sha256=manifest["spec_hash"],
        runtime_versions=manifest["versions"], observation_contract="nanfo.passive-measured-v4.v1",
        runtime_action="linux-frr-host-route", action_ids=["route0", "route1"],
        scopes=[dict(network_id=str(network), workspace_id=str(workspace), snapshot_path="snapshot.json")],
        installed_at=(now - timedelta(seconds=10)).isoformat(), expires_at=(now + timedelta(hours=1)).isoformat(),
        max_observation_age_seconds=30, plan=ref(f"{BENCHMARK}/plan.json"),
        selection=ref(f"{BENCHMARK}/selection.json"), report=ref(f"{BENCHMARK}/test-report.json"),
        sessions=[dict(summary=ref(f"{BENCHMARK}/test-{policy}/summary.json"),
                       evidence=ref(f"{BENCHMARK}/test-{policy}/evidence.jsonl")) for policy in plan["policy_order"]])
    content = json.dumps(document).encode()
    registry_path = tmp_path / "registry.json"
    registry_path.write_bytes(content)
    registry_path.chmod(0o600)
    settings = LiveSettings(str(registry_path), hashlib.sha256(content).hexdigest(), str(ROOT),
                            str(ROOT / ".venv/bin/python"), str(observations))
    if snapshot:
        # UNIT FIXTURE ONLY: replaying historical bytes with test timestamps is not a
        # real operator installation and must never be published as live evidence.
        history = json.loads((ROOT / HISTORY).read_bytes())
        body = dict(version="nanfo.passive-measured-v4.v1", network_id=str(network), workspace_id=str(workspace),
            snapshot_id=str(uuid.uuid4()), run_id=history["frames"][0]["response"]["data"]["episode_id"],
            observed_at=(now - timedelta(seconds=1)).isoformat(), window_started_at=(now - timedelta(seconds=4)).isoformat(),
            published_at=now.isoformat(), source="operator-attested-measured-lab", contract_sha256=manifest["contract_hash"],
            spec_sha256=manifest["spec_hash"], history=history, history_sha256=canonical_hash(history))
        (observations / "snapshot.json").write_text(json.dumps(body))
        (observations / "snapshot.json").chmod(0o600)
    return LiveRegistry(settings), network, workspace, document
