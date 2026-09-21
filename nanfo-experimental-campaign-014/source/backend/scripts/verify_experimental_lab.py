"""ADR025 preregistration and bounded joined-loop acceptance coordinator.

Preparation is offline. Launch requires a separate, exact-plan parent admission.
Historical qualification is an input identity, never this campaign's outcome.
"""

import argparse
import asyncio
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import stat
import subprocess
import sys
import time
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
MODEL = ROOT / "ai-engine/artifacts/adr024-qualified-001/model"
LOCK = Path("/tmp/opencode/nanfo-privileged-lab-slot.lock")
VERSION = "nanfo.experimental-acceptance/v1"
CHECKPOINT = "77dae44acab722a5a6a2e87d952a6cca65e1c4eea102a089830a8401b521d614"
REPORT = "e6ee9c1bd99e3f6961db497db664335684fa277bd1a1c86a8034570ac116056d"
REDIS_IMAGE = "sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2"
POLICIES = ("qualified", "fixed0", "fixed1", "heuristic")
SCENARIOS = ("path0", "path1")
OUTCOME_PROTOCOL = "nanfo.experimental-outcomes/v2"


def ai_interpreter():
    marker = ROOT / "frozen-runtime.json"
    return Path(read(marker)["ai_interpreter"]["path"]) if marker.exists() else ROOT / "ai-engine/.venv/bin/python"


def freeze_runtime(output):
    """Copy the entire runnable source family and preserved model, never symlinks/env."""
    if output.resolve().is_relative_to(ROOT) and not (
            output.parent.resolve()==(ROOT/"ai-engine/artifacts").resolve()
            and output.name.startswith("adr025-runtime-")):
        raise ValueError("snapshot_requires_external_or_dedicated_ignored_artifact_root")
    files = []
    excluded = {".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules",
                ".git", "output", "htmlcov", "test-results"}
    for relative in ("backend", "emulation", "scripts", "deploy",
                     "ai-engine/artifacts/adr024-qualified-001"):
        base = ROOT / relative
        for directory, dirs, names in os.walk(base, followlinks=False):
            parent = Path(directory)
            dirs[:] = sorted(d for d in dirs if d not in excluded and not (parent/d).is_symlink())
            for name in sorted(names):
                path = parent/name
                if (name.startswith(".") or name in {"redis.conf"}
                        or path.suffix in {".pyc", ".log", ".pem", ".key", ".p12", ".pfx"}):
                    continue
                if relative != "ai-engine/artifacts/adr024-qualified-001" and path.suffix not in {
                    ".py",".toml",".lock",".txt",".json",".jsonl",".yaml",".yml",".ini",".cfg",".sql",".sh",".md"
                } and not name.startswith("Dockerfile"):
                    continue
                if path.is_symlink():
                    raise ValueError("snapshot_symlink_input:"+str(path.relative_to(ROOT)))
                if path.is_file():
                    files.append(path)
    if sum(p.stat().st_size for p in files) > 512 * 1024**2:
        raise ValueError("snapshot_size_bound")
    pins = {str(p.relative_to(ROOT)): digest(p) for p in files}
    output.mkdir(mode=0o700, exist_ok=False)
    for path in files:
        relative = path.relative_to(ROOT)
        target = output/relative
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != pins[str(relative)]:
            raise ValueError("source_changed_during_snapshot")
        fd = os.open(target, os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd,"wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    review = Path("/tmp/opencode/test_adr025_integrated_review.py")
    if review.exists():
        content=review.read_bytes()
        target=output/"backend/tests/frozen_independent_review.py"
        target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        with target.open("xb") as stream:
            stream.write(content)
        pins[str(target.relative_to(output))]=hashlib.sha256(content).hexdigest()
    interpreter = ai_interpreter().absolute()
    marker = dict(version="nanfo.experimental-frozen-runtime/v1", source_origin=str(ROOT),
        created_ns=time.time_ns(), files=pins, ai_interpreter=dict(path=str(interpreter),sha256=digest(interpreter)),
        seed_inventory_origins=[str(p) for p in history_roots()],
        model_origin=str(MODEL), model_snapshot=str(output / MODEL.relative_to(ROOT)),
        source_policy="execute-only-this-snapshot; workspace never searched for executable imports",
        excluded="credentials/.env, caches, generated output, symlink directories, bytecode")
    # A producer changing any copied source during publication invalidates this snapshot.
    if any(digest(path) != pins[str(path.relative_to(ROOT))] for path in files):
        write(output/"snapshot-invalid.json",dict(reason="source_changed_during_snapshot",candidate_manifest=marker))
        raise ValueError("source_changed_during_snapshot")
    write(output/"frozen-runtime.json", marker)
    verify_runtime_snapshot(output)
    return dict(status="prepared", root=str(output), manifest_sha256=digest(output/"frozen-runtime.json"), files=len(pins))


def verify_runtime_snapshot(root=ROOT):
    marker = root/"frozen-runtime.json"
    if not marker.exists():
        raise ValueError("live_campaign_requires_frozen_runtime")
    value = read(marker)
    for relative,pin in value["files"].items():
        path = root/relative
        if Path(relative).is_absolute() or ".." in Path(relative).parts or path.is_symlink() or digest(path)!=pin:
            raise ValueError("frozen_runtime_payload_changed:"+relative)
    interpreter = value["ai_interpreter"]
    if digest(Path(interpreter["path"])) != interpreter["sha256"]:
        raise ValueError("frozen_ai_interpreter_changed")
    return value


def read(path):
    return json.loads(Path(path).read_bytes())


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, value):
    data = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(data).hexdigest()


def exception_evidence(exc, directory):
    """Preserve the exception chain and frames without credentials or SQL params."""
    import traceback
    secrets = [v for k, v in os.environ.items() if any(s in k.upper() for s in ("PASSWORD", "SECRET", "TOKEN", "DSN", "URL")) and len(v) > 3]
    token = directory / "receiver-token"
    if token.exists():
        secrets.append(token.read_text().strip())
    rows, seen = [], set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        message = str(exc)
        if hasattr(exc, "params"):
            message = "database exception; SQL parameters withheld"
        for value in secrets:
            message = message.replace(value, "[credential withheld]")
        rows.append(dict(type=type(exc).__name__, message=message[:8000],
            frames=[dict(file=Path(f.filename).name, line=f.lineno, function=f.name)
                    for f in traceback.extract_tb(exc.__traceback__)]))
        exc = exc.__cause__ or exc.__context__
    return rows


@contextmanager
def campaign_slot():
    """The common inode is never unlinked/replaced; no privileged work before flock."""
    fd = os.open(LOCK, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("unsafe_campaign_lock")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def seed_values(value, key=""):
    if isinstance(value, dict):
        return set().union(*(seed_values(child, name) for name, child in value.items()))
    if isinstance(value, list):
        return set().union(*(seed_values(child, key) for child in value))
    return {value} if type(value) is int and "seed" in key.lower() and 0 <= value < 2**31 else set()


def history_roots():
    """Include unsuccessful/temp campaigns, not just the preserved winning report."""
    marker = ROOT/"frozen-runtime.json"
    roots = ([Path(p) for p in read(marker)["seed_inventory_origins"]] if marker.exists() else
             [ROOT / "ai-engine/artifacts", ROOT / "emulation/output",
             ROOT / "docs/project/CompletionProgram"])
    for path in sorted(Path("/tmp/opencode").iterdir()):
        if path.name.startswith(("nanfo-adr024-evaluation-", "nanfo-live-acceptance-",
                                 "nanfo-experimental-campaign-", "nanfo-adr025-", "native-driver-")):
            if path.is_dir() and not path.is_symlink():
                roots.append(path)
            elif path.suffix in {".json", ".jsonl"}:
                roots.append(path)
    return list(dict.fromkeys(roots))


def reject_new_seed_reservations(output, plan):
    """A prepared plan is a reservation; do not race another later acquisition."""
    saved = read(output / "seed-audit.json")
    known = {row["path"]: row["sha256"] for row in saved["documents"]}
    current = audit_seeds([root for root in history_roots() if root.resolve() != output.resolve()])
    selected = {row["seed"] for row in plan["trials"] + plan["faults"] + plan.get("smoke", [])}
    for row in current["documents"]:
        if known.get(row["path"]) != row["sha256"] and selected.intersection(row["seeds"]):
            raise ValueError("new_conflicting_operational_seed_reservation")


def audit_seeds(roots):
    reserved, documents, seen, exclusions = set(), [], set(), []
    for root in roots:
        if not root.exists():
            raise ValueError("seed_audit_root_missing:" + str(root))
        if root.name.startswith("native-driver-"):
            protocol = read(root / "protocol.json")
            source = root / "source/backend/scripts/verify_native_driver.py"
            if (protocol.get("version") == "nanfo.native-driver-acceptance/v1"
                    and protocol.get("fixture") == "static-FIB-no-OSPF"
                    and protocol.get("authority_kind") == "scoped-manual-driver-campaign"
                    and not seed_values(protocol)
                    and digest(source) == protocol["source_sha256"]["backend/scripts/verify_native_driver.py"]):
                exclusions.append(dict(root=str(root), protocol_sha256=digest(root / "protocol.json"),
                    source_sha256=digest(source), reason="manual-static-FIB-action-prefix-campaign-no-model-seeds",
                    excluded="native syscall/results/setup evidence; protocol retained in seed inventory"))
                paths = [root / "protocol.json"]
            else:
                raise ValueError("native_campaign_seed_exclusion_not_proven")
        else:
            # pathlib does not recurse symlink directories; make that rule explicit.
            paths = [root] if root.is_file() else sorted(root.rglob("*"))
        for path in paths:
            if path.suffix not in {".json", ".jsonl", ".ptz"} or not path.is_file():
                continue
            if path.is_symlink():
                raise ValueError("seed_audit_symlink:" + str(path))
            identity = path.resolve()
            if identity in seen:
                continue
            seen.add(identity)
            found = set()
            if path.suffix == ".ptz":
                with zipfile.ZipFile(path) as bundle:
                    for name in bundle.namelist():
                        if name.endswith(".json"):
                            found.update(seed_values(json.loads(bundle.read(name))))
            else:
                with path.open("rb") as stream:
                    if path.suffix == ".jsonl":
                        for line in stream:
                            if line.strip():
                                found.update(seed_values(json.loads(line)))
                    else:
                        found.update(seed_values(json.load(stream)))
            reserved.update(found)
            documents.append(dict(path=str(identity), sha256=digest(path), seeds=sorted(found)))
    return dict(version=1, roots=[str(p) for p in roots], documents=documents, exclusions=exclusions,
                reserved_seeds=sorted(reserved))


def model_identity(root):
    template = read(root / "live-registry.template.json")
    if template["checkpoint"]["sha256"] != CHECKPOINT or template["report"]["sha256"] != REPORT:
        raise ValueError("wrong_recovered_qualified_model")
    pins = {}

    def visit(value):
        if isinstance(value, dict):
            if {"path", "sha256", "size_bytes"} <= value.keys():
                path = root / value["path"]
                if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
                    raise ValueError("model_reference_escape")
                if path.stat().st_size != value["size_bytes"] or digest(path) != value["sha256"]:
                    raise ValueError("model_reference_changed:" + value["path"])
                pins[value["path"]] = value["sha256"]
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(template)
    for name, pin in template["source_sha256"].items():
        path = root / template["source_directory"] / name
        if digest(path) != pin:
            raise ValueError("frozen_source_changed")
        pins[str(path.relative_to(root))] = pin
    pins["live-registry.template.json"] = digest(root / "live-registry.template.json")
    return dict(root=str(root.resolve()), files=pins, checkpoint_sha256=CHECKPOINT,
                report_sha256=REPORT, image_id=read(root / "plan.json")["image_id"],
                weights_sha256=read(root / "lineage.json")["tensor_payload_sha256"])


def source_pins():
    if (ROOT/"frozen-runtime.json").exists():
        manifest = read(ROOT/"frozen-runtime.json")
        return {name:digest(ROOT/name) for name in manifest["files"] if not name.startswith("ai-engine/artifacts/")}
    files = {Path(__file__), ROOT / "backend/scripts/audit_experimental_lab.py",
             ROOT / "backend/scripts/frozen_live_inference.py",
             ROOT / "backend/scripts/verify_measured_twin.py",
             *ROOT.glob("backend/app/modules/autonomy/*.py"),
             *ROOT.glob("backend/app/modules/autonomy/experimental/*.py"),
             *ROOT.glob("backend/app/modules/simulation/*.py"),
             *ROOT.glob("backend/app/modules/identity/*.py"),
             *ROOT.glob("backend/app/modules/network/*.py"),
             *ROOT.glob("backend/app/core/*.py"),
             *ROOT.glob("backend/alembic/versions/*.py"),
             ROOT / "backend/scripts/acceptance/runtime.py",
             ROOT / "backend/scripts/acceptance/common.py",
             ROOT / "backend/scripts/frozen_model_diagnostic.py",
             ROOT / "backend/poetry.lock",
             ROOT / "backend/tests/unit/test_experimental_campaign.py",
             ROOT / "backend/tests/unit/test_experimental_lab.py",
             ROOT / "backend/tests/unit/test_experimental_lab_adapter.py",
             ROOT / "backend/tests/unit/test_experimental_simulation.py",
             ROOT / "backend/tests/unit/test_experimental_simulation_raw.py",
             ROOT / "backend/tests/experimental_lab_support.py",
             ROOT / "emulation/tests/test_experimental_lab.py",
             *ROOT.glob("emulation/experimental_lab*.py")}
    return {str(path.relative_to(ROOT)): digest(path) for path in sorted(files)}


def validate_native_projection(value):
    """Offline strict receiver validation using the actual owner's protected parser."""
    import tempfile
    from emulation.experimental_lab_contract import load_policy
    with tempfile.TemporaryDirectory(prefix="experimental-projection-", dir="/tmp/opencode") as name:
        path = Path(name) / "policy.json"
        pin = write(path, value)
        return load_policy(str(path), pin)


def campaign_receiver_class():
    """Campaign-only setup instrumentation around the owner's unchanged receiver.

    No new wire operation: status exposes read-only baseline; bootstrap optionally
    consumes original step1 under its existing explicit operator authority.
    """
    try:
        from experimental_lab_receiver import Receiver
        from experimental_lab_contract import digest as native_digest, protected_read
    except ImportError:
        from emulation.experimental_lab_receiver import Receiver
        from emulation.experimental_lab_contract import digest as native_digest, protected_read

    class CampaignReceiver(Receiver):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.runtime.capture_baseline()
            original_capture = self.runtime.capture_baseline

            def capture_once():
                if self.runtime.baseline is None:
                    return original_capture()
                current = self.runtime.original_readback()
                if (current["tables"] != self.runtime.baseline["tables"]
                        or any(current["paths"][k]["nodes"] != v["nodes"]
                               for k, v in self.runtime.baseline["paths"].items())):
                    raise ValueError("prebootstrap_baseline_changed")
                return self.runtime.baseline
            self.runtime.capture_baseline = capture_once
            self.checkpoint_events = []

        def handle(self, raw):
            response = super().handle(raw)
            if json.loads(raw)["operation"] == "status":
                response["evidence"].update(baseline=self.runtime.baseline,
                    baseline_sha256=native_digest(self.runtime.baseline))
            return response

        def dispatch_authority(self, entry):
            super().authority()
            # Native writes require a just-completed owning-service checkpoint,
            # requested after WAL and before original dispatch. No cached grant.
            if (self.runtime.restoring or not self.runtime.transcript
                    or entry is not self.runtime.transcript[-1]
                    or entry["completed"] is not None or entry["argv"][2] != "add"):
                raise ValueError("invalid_writer_dispatch_checkpoint")
            try:
                from experimental_lab_contract import atomic_write
            except ImportError:
                from emulation.experimental_lab_contract import atomic_write
            identity = native_digest({"entry":entry, "request_id":self.current.request_id})
            atomic_write(self.directory / "checkpoint-request.json", {"id":identity, "entry":entry,
                         "request_id":self.current.request_id})
            deadline = time.monotonic()+5
            while time.monotonic()<deadline:
                super().authority()
                path = self.directory / "checkpoint-response.json"
                if path.exists():
                    response = json.loads(protected_read(path))
                    if response.get("id") == identity:
                        self.checkpoint_events.append({"id":identity,"authorized":response.get("authorized"),
                            "entry":dict(entry),"checked_monotonic":time.monotonic()})
                        if response.get("authorized") is not True:
                            raise ValueError("current_core_authority_denied")
                        super().authority()
                        return
                time.sleep(.02)
            raise ValueError("current_core_authority_timeout")

        def persist(self):
            super().persist()
            if hasattr(self, "checkpoint_events"):
                try:
                    from experimental_lab_contract import atomic_write
                except ImportError:
                    from emulation.experimental_lab_contract import atomic_write
                atomic_write(self.directory / "campaign-authority.json", self.checkpoint_events)

        def operate(self, req):
            result = super().operate(req)
            if req.operation == "bootstrap":
                setup = json.loads(protected_read(self.directory / "campaign-setup.json"))
                if (set(setup) != {"receiver_policy_sha256", "initial_action", "campaign_source_sha256"}
                        or setup["receiver_policy_sha256"] != self.policy_hash
                        or setup["initial_action"] not in (0, 1)
                        or setup["campaign_source_sha256"] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest()):
                    raise ValueError("campaign_setup_not_pinned")
                if setup["initial_action"] == 1:
                    self.phase = "bootstrapping"
                    self.persist()
                    warm = self.runtime.frame(1)
                    self.last_frame = warm
                    self.phase = "bootstrapped"
                    result = {**warm, "episode_id": self.runtime.experiment.episode,
                        "baseline": self.runtime.baseline, "baseline_sha256": native_digest(self.runtime.baseline),
                        "initial_reset": result, "operator_warmup_action": 1}
                    self.persist()
            return result
    return CampaignReceiver


def receiver_main(directory, policy_hash):
    """Runs only inside the admitted exact image, with owner CLI validation intact."""
    import experimental_lab_receiver as owner
    original_load = owner.load_original
    def load(source):
        module = original_load(source)
        original_lab = module.OspfLab
        class CampaignLab(original_lab):
            def start(self):
                # Original FRR drops to frr: its parent/config files must have the
                # same traversable/readable modes as original image startup.
                previous = os.umask(0o022)
                try:
                    return super().start()
                finally:
                    os.umask(previous)
        module.OspfLab = CampaignLab
        return module
    owner.load_original = load
    owner.Receiver = campaign_receiver_class()
    return owner.main(["--directory", directory, "--policy", directory + "/receiver-policy.json",
        "--policy-sha256", policy_hash, "--token", directory + "/receiver-token",
        "--source-directory", "/opt/nanfo/emulation"])


def simulation_policy():
    """Declared fluid assumptions; no sampled packet-peak to queue-byte conversion."""
    links = []
    for branch in (1, 2):
        for source, target, node, interface in (
            ("access1", f"dist{branch}", "access1", f"access1-eth{branch}"),
            (f"dist{branch}", "access2", f"dist{branch}", f"dist{branch}-eth4"),
        ):
            links.append(dict(link_id=f"{source}-{target}", source=source, target=target,
                capacity_source="htb_readback",
                node=node, interface=interface, buffer_bytes=120000.0, initial_queue_bytes=0.0,
                delay_ms=5.0, source_label="operator_configured_model"))
    paths = [[f"access1-dist{n}", f"dist{n}-access2"] for n in (1, 2)]
    return dict(assumptions=dict(version=1, links=links, foreground_paths=paths,
        background_path=paths[0], tick_ms=10, duration_ticks=200),
        objectives=dict(max_loss_pct=75.0, max_latency_ms=1000.0, min_throughput_mbps=0.1))


def fault_matrix():
    cases = []
    for scenario in SCENARIOS:
        for name, mechanism, phase, index in (
            ("delayed-data", "real", "beforewrite", 0),
            ("STOP-before", "real", "beforewrite", 0),
            ("STOP-after", "real", "afterwrite", 1),
            ("revoke-before", "real", "beforewrite", 0),
            ("revoke-after", "real", "afterwrite", 1),
            ("link-failure", "real", "afterwrite", 1),
            ("disconnect", "real", "afterwrite", 1),
            ("restart", "real", "afterwrite", 1),
            ("partial-apply", "injected_failpoint", "afterwrite", 1),
            ("ambiguous-receipt", "injected_failpoint", "afterwrite", 1),
        ):
            cases.append(dict(case_id=f"{scenario}-{name}", scenario=scenario, fault=name,
                              intervention=mechanism, phase=phase, write_index=index,
                              bootstrap_initial_action=0 if scenario == "path0" else 1))
    return cases


def prepare(output, *, model=MODEL, roots=None, pairs=6, budget_seconds=7200, gate_evidence=None):
    if not 2 <= pairs <= 12:
        raise ValueError("paired_seed_count_out_of_bounds")
    if not 2400 <= budget_seconds <= 14400:
        raise ValueError("campaign_budget_out_of_bounds")
    identity = model_identity(model)
    if gate_evidence is not None:
        gate = read(gate_evidence)
        if gate["status"] != "passed" or gate["source_sha256"] != source_pins() or gate["privileged_launch"] is not False:
            raise ValueError("offline_gate_evidence_not_current")
    audit = audit_seeds(history_roots() if roots is None else roots)
    reserved = set(audit["reserved_seeds"])
    # Frozen train split is [1000, 2000). These are operational evaluation, not training.
    seeds = [s for s in range(1000, 2000) if s not in reserved][:pairs * 2 + 24]
    if len(seeds) != pairs * 2 + 24:
        raise ValueError("unused_operational_seeds_exhausted")
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    seed_hash = write(output / "seed-audit.json", audit)
    trials = []
    order = random.Random(25092026)
    for index, seed in enumerate(seeds[:pairs * 2]):
        scenario = SCENARIOS[index % 2]
        policies = list(POLICIES)
        order.shuffle(policies)
        for policy in policies:
            trials.append(dict(case_id=f"{scenario}-{seed}-{policy}", seed=seed,
                               scenario=scenario, policy=policy))
    faults = [item | {"seed": seed, "policy": "qualified"}
              for item, seed in zip(fault_matrix(), seeds[pairs * 2:pairs * 2+20], strict=True)]
    smoke = [dict(case_id=f"smoke-{scenario}-{policy}-{seed}", seed=seed, scenario=scenario,
                  policy=policy, stage="smoke") for (policy,scenario),seed in zip(
                      [(p,s) for p in ("qualified","heuristic") for s in SCENARIOS], seeds[-4:], strict=True)]
    plan = dict(version=VERSION, campaign_id=uuid.uuid4().hex, created_ns=time.time_ns(),
        model=identity, seed_audit_sha256=seed_hash, policies=list(POLICIES), trials=trials,
        faults=faults, smoke=smoke, smoke_rule="two-model-keeps-two-heuristic-audited-outcomes-before-matrix; separate-seeds-not-counted",
        outcome_protocol=OUTCOME_PROTOCOL,
        outcome_rules=dict(accepted=["kept_then_restored","simulation_rejected","performance_rejected_then_restored"],
            unaccepted=["measurement_invalid","control_failure","recovery_uncertain","not_run"],
            applies_to="all four selectors with identical numerical/authority/restoration gates",
            missing_metrics="null; every preregistered seed remains in denominator",
            smoke="both model directions must keep; heuristics may reject only with complete raw proof",
            max_action_seconds=30, one_action=True),
        runtime_snapshot_sha256=digest(ROOT/"frozen-runtime.json") if (ROOT/"frozen-runtime.json").exists() else None,
        migration_target="0029",
        split="train", training=False, calibrated=False,
        scope="experimental-disposable-lab-only", steps=4, window_seconds=2.0,
        paired_seeds_per_direction=pairs, budget_seconds=budget_seconds, cleanup_reserve_seconds=180,
        case_budget_seconds=180, max_observation_age_seconds=30, max_action_seconds=30,
        lease_seconds=65, io_timeout_seconds=60, bootstrap_budget_seconds=90,
        minimum_dwell_seconds=2, max_actions_per_case=1, order_seed=25092026,
        frame_budget=dict(reset=1, apply=1, verify=1, reserved=1),
        redis_image_id=REDIS_IMAGE,
        heuristic_rule="least-utilization-then-queue/v1",
        source_sha256=source_pins(),
        offline_gates_sha256=None if gate_evidence is None else digest(gate_evidence),
        simulation=simulation_policy(),
        fault_scope="nonstationary interventions outside original stationary benchmark; explicit wrapper evidence",
        wrapper_scope="receiver + separately source-pinned campaign baseline/status/bootstrap and per-add current-core checkpoint instrumentation",
        thresholds=dict(min_goodput_mbps=0.1, max_udp_loss_fraction=0.75, max_probe_loss_fraction=0.75,
                        max_probe_rtt_ms=1000, min_probe_sent=3, min_traffic_bytes=1),
        performance_rule="report-all-paired-seed-deltas-no-superiority-gate-no-retuning",
        retry_rule="one-attempt-per-case-preserve-all-failures-no-execute-replay",
        launch_requires="parent-core-adapter-ready-and-exact-plan-admission")
    write(output / "plan.json", plan)
    if gate_evidence is not None:
        with (output / "offline-gates.json").open("xb") as stream:
            stream.write(gate_evidence.read_bytes())
    for relative, pin in plan["source_sha256"].items():
        target = output / "source" / relative
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        content = (ROOT / relative).read_bytes()
        if hashlib.sha256(content).hexdigest() != pin:
            raise ValueError("source_changed_during_preregistration")
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    return plan


@contextmanager
def private_services(output):
    """Reuse owned PostgreSQL/Redis lifecycle; no dependency/auth provider overrides."""
    import tempfile
    from scripts.verify_measured_twin import LocalLab, command, environment

    redis_binary = shutil.which("redis-server")
    if not shutil.which("initdb") or not shutil.which("postgres"):
        raise ValueError("private_postgres_redis_binaries_required")
    private = Path(tempfile.mkdtemp(prefix="nanfo-experimental-services-", dir="/tmp/opencode"))
    lab = LocalLab(private, redis_binary, None if redis_binary else read(output / "plan.json")["redis_image_id"])
    lab.env.update(PYTHONPATH=str(ROOT/"backend")+os.pathsep+str(ROOT),PYTHONNOUSERSITE="1")
    try:
        lab.start_postgres()
        lab.start_redis()
        target = read(output/"plan.json")["migration_target"]
        if target != "0029":
            raise ValueError("reviewed_retention_migration_required")
        migration = ("from alembic.config import Config; from alembic import command; "
                     "c=Config(); c.set_main_option('script_location', 'alembic'); command.upgrade(c, '0029')")
        if command([sys.executable, "-c", migration], lab.env, timeout=90):
            raise ValueError("private_experimental_migration_failed")
        with environment(lab.env):
            from app.core.config import get_settings
            get_settings.cache_clear()
            yield lab
    finally:
        cleanup = lab.cleanup()
        write(output / "private-services-cleanup.json", cleanup)
        from app.core.config import get_settings
        get_settings.cache_clear()


async def provision_actor(sessions, redis):
    """Owning Identity login and current Network permission, real stores only."""
    import secrets
    from app.core.security import hash_password
    from app.modules.identity.repository import UserRepository
    from app.modules.identity.service import AuthService
    from app.modules.organization.models import Organization, OrgMember, Workspace
    from app.modules.network.models import Network

    org, workspace, network = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    password = secrets.token_urlsafe(32)
    email = f"experimental-{uuid.uuid4().hex}@example.com"
    async with sessions() as db:
        users = UserRepository(db)
        user = await users.create(email, hash_password(password))
        await users.assign_role(user.user_id, "Admin")
        db.add(Organization(org_id=org, name="Private ADR025 lab", slug=uuid.uuid4().hex))
        await db.flush()
        db.add_all([Workspace(workspace_id=workspace, org_id=org, name="Experimental lab"),
                    OrgMember(org_id=org, user_id=user.user_id, org_role="Admin"),
                    Network(network_id=network, workspace_id=workspace, name="Disposable joined loop")])
        await db.commit()
        auth = AuthService(db, redis)
        token = await auth.login(email, password, "127.0.0.1", str(uuid.uuid4()))
        claims = await auth.authenticate_access(token.access_token)
        await db.commit()
    return dict(actor_id=str(user.user_id), network_id=str(network), workspace_id=str(workspace),
                org_id=str(org), login_authenticated=True,
                current_permissions=claims["permissions"], backend="real-private-postgres-redis")


class CapturedPorts:
    """Instrument real owner ports; complete return values are retained unchanged."""

    def __init__(self, ports, directory, registry, observations):
        self.ports, self.directory = ports, directory
        self.registry, self.observations = registry, observations
        self.records, self.timings = {}, []

    def bind_checkpoint(self, checkpoint):
        self.ports.bind_checkpoint(checkpoint)

    async def call(self, name, method, *args):
        began = time.monotonic_ns()
        try:
            result = await method(*args)
            index = sum(1 for row in self.timings if row["operation"] == name)
            filename = f"{name}-{os.getpid()}-{index}.json"
            pin = write(self.directory / filename, result.model_dump(mode="json"))
            self.records[name] = dict(path=filename, sha256=pin)
            return result
        finally:
            self.timings.append(dict(operation=name, started_ns=began, finished_ns=time.monotonic_ns()))

    async def observe(self):
        # Publication is passive: the sole owner adapter acquired this exact frame.
        frame = await self.ports.observer.observe()
        from app.modules.autonomy.schemas import contract_digest
        snapshot = frame.snapshot
        data = json.dumps(snapshot.model_dump(mode="json"), sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode()
        fd = os.open(self.observations / "snapshot.json", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        observation = frame.observation.model_copy(update={"evidence": [
            *frame.observation.evidence, "passive_snapshot:" + contract_digest(snapshot),
            "live_registry:" + self.registry]})
        frame = frame.model_copy(update={"observation": observation})
        pin = write(self.directory / "frame.json", frame.model_dump(mode="json"))
        self.records["frame"] = dict(path="frame.json", sha256=pin)
        if (self.directory / "fault-case.json").exists():
            case = read(self.directory / "fault-case.json")
            if case["fault"] == "delayed-data":
                write(self.directory / "observation-ready.json", {"monotonic_ns": time.monotonic_ns()})
                await wait_file(self.directory / "observation-release.json", timeout=45)
        return frame

    async def infer(self, frame):
        return await self.call("inference", self.ports.model.infer, frame)

    async def simulate(self, *args):
        return await self.call("simulation", self.ports.simulator.simulate, *args)

    async def prepare(self, *args):
        return await self.call("prepared", self.ports.transport.prepare, *args)

    async def execute(self, *args):
        write(self.directory / "execute-ready.json", {"monotonic_ns": time.monotonic_ns()})
        if (self.directory / "fault-case.json").exists():
            async with asyncio.timeout(45):
                while not (self.directory / "execute-release.json").exists():
                    await asyncio.sleep(.05)
        return await self.call("receipt", self.ports.transport.execute, *args)

    async def verify(self, *args):
        return await self.call("verification", self.ports.transport.verify, *args)

    async def recover(self, *args):
        return await self.call("recovery", self.ports.transport.recover, *args)

    async def recover_bootstrap(self, *args):
        return await self.call("bootstrap_recovery", self.ports.transport.recover_bootstrap, *args)


class CampaignTransport:
    """Bootstrap receipt bridge; normal action calls remain the owner's adapter."""

    def __init__(self, adapter, owner):
        self.adapter, self.owner = adapter, owner

    def bind_checkpoint(self, checkpoint):
        self.adapter.bind_checkpoint(checkpoint)
        self.owner.checkpoint = checkpoint

    async def observe(self):
        return await self.adapter.observe()

    async def prepare(self, command):
        return await self.adapter.prepare(command)

    async def execute(self, action, checkpoint):
        previous = self.owner.checkpoint
        self.owner.checkpoint = checkpoint
        try:
            return await self.adapter.execute(action, checkpoint)
        finally:
            self.owner.checkpoint = previous

    async def verify(self, action):
        return await self.adapter.verify(action)

    async def recover(self, action, checkpoint):
        return await self.adapter.recover(action, checkpoint)

    async def recover_bootstrap(self, command, checkpoint):
        from app.modules.autonomy.experimental.schemas import BootstrapRecoveryReceipt, contract_digest
        await self.adapter.close()
        await checkpoint()
        await self.owner.request("status")
        evidence = await self.owner.request("recover")
        restoration = evidence.get("restoration", {})
        readback = restoration.get("readback", {})
        exact = (restoration.get("baseline_sha256") == command.baseline_sha256
            and restoration.get("baseline") == command.baseline and restoration.get("owned_empty") is True
            and readback.get("tables") == command.baseline["tables"]
            and all(readback.get("paths", {}).get(k, {}).get("nodes") == v["nodes"]
                    for k, v in command.baseline["paths"].items()))
        return BootstrapRecoveryReceipt(request_id=command.request_id, command_sha256=contract_digest(command),
            baseline_sha256=command.baseline_sha256, ownership_sha256=command.ownership_sha256,
            status="restored" if exact else "uncertain", evidence=evidence)


def campaign_adapter_class():
    from app.modules.autonomy.experimental.adapter import ExperimentalLabAdapter
    from app.modules.autonomy.experimental.schemas import MeasuredFrame, contract_digest
    from app.modules.autonomy.live_schemas import PassiveSnapshot
    from app.modules.autonomy.schemas import Observation
    from datetime import UTC, datetime

    class CampaignAdapter(ExperimentalLabAdapter):
        async def _guarded(self, operation, checkpoint, **kwargs):
            await self._heartbeat(checkpoint)
            task = asyncio.create_task(self._call(operation, **kwargs))
            try:
                while not task.done():
                    done, _ = await asyncio.wait({task}, timeout=1.)
                    if not done:
                        await self._heartbeat(checkpoint)
                return await task
            except BaseException:
                try:
                    await asyncio.shield(self._call("stop"))
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                raise

        async def _maintain_authority(self):
            try:
                while True:
                    await asyncio.sleep(1.)
                    await self._heartbeat(self.current_authority)
            except asyncio.CancelledError:
                raise
            except Exception:
                try:
                    await self._call("stop")
                except Exception:
                    return

        async def _sync(self):
            result = await self._call("status")
            binding = result.get("binding")
            if (not binding or binding["controller_policy_sha256"] != contract_digest(self.policy)
                    or binding["receiver_policy_sha256"] != self.policy_hash):
                raise ValueError("campaign_bootstrap_binding_invalid")
            self.measurement_run_id = uuid.UUID(binding["run_id"])
            self.fence = max(self.fence, result["current_fence"])
            self.synced = True

        async def observe(self):
            evidence = await self._guarded("observe", self.current_authority)
            if self.keepalive is None:
                self.keepalive = asyncio.create_task(self._maintain_authority())
            self.baseline = evidence
            raw = evidence["frame"]
            data = raw["response"]["data"]
            if uuid.UUID(data["episode_id"]) != self.measurement_run_id:
                raise ValueError("campaign_actual_episode_changed")
            observed, started = self._times(evidence)
            now = datetime.now(UTC)
            history = {"version":3, "frames":[raw]}
            snapshot = PassiveSnapshot(version="nanfo.passive-measured-v4.v1",
                network_id=self.policy.network_id, workspace_id=self.policy.workspace_id,
                snapshot_id=uuid.uuid4(), run_id=self.measurement_run_id, observed_at=observed,
                window_started_at=started, published_at=now, source="operator-attested-measured-lab",
                contract_sha256=self.receiver_contract_hash, spec_sha256=data["evidence"]["spec_hash"],
                history=history, history_sha256=contract_digest(history))
            age = (now-observed).total_seconds()
            if not 0 <= age <= self.policy.max_observation_age_seconds:
                raise ValueError("campaign_observation_stale")
            return MeasuredFrame(snapshot=snapshot, runtime=self.policy.runtime, features=data["observation"],
                observation=Observation(network_id=self.policy.network_id, workspace_id=self.policy.workspace_id,
                    provider_id="experimental_owned_v4", contract=snapshot.version, observed_at=observed,
                    collected_at=now, age_seconds=age, fresh=True, compatible=True, evidence=["raw:"+snapshot.history_sha256]),
                provenance=evidence)
    return CampaignAdapter


async def export_journal(sessions, run_id, path):
    from sqlalchemy import select
    from app.modules.autonomy.experimental.models import LabAction, LabReceipt, LabRun

    def row(value):
        return {column.name: (v.isoformat() if hasattr(v, "isoformat") else str(v) if isinstance(v, uuid.UUID) else v)
                for column in value.__table__.columns
                if column.name != "lease_token" and (v := getattr(value, column.name)) is not None}
    async with sessions() as db:
        run = await db.get(LabRun, run_id)
        actions = (await db.scalars(select(LabAction).where(LabAction.run_id == run_id))).all()
        receipts = (await db.scalars(select(LabReceipt).where(LabReceipt.run_id == run_id)
                                   .order_by(LabReceipt.created_at, LabReceipt.receipt_id))).all()
        return write(path, dict(run=None if run is None else row(run), actions=[row(a) for a in actions],
                               receipts=[row(r) for r in receipts]))


async def start_controller_child(directory, operation):
    import secrets
    launch_key = secrets.token_hex(32)
    write(directory / f"child-admission-{operation}.json", {"key_sha256": hashlib.sha256(launch_key.encode()).hexdigest()})
    child = await asyncio.create_subprocess_exec(sys.executable, "-B", "-m", "scripts.verify_experimental_lab",
        "child", "--output", str(directory), "--child-operation", operation,
        cwd=ROOT / "backend", env={**os.environ, "NANFO_EXPERIMENTAL_CHILD": launch_key,
            "PYTHONPATH":str(ROOT/"backend")+os.pathsep+str(ROOT), "PYTHONNOUSERSITE":"1"}, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    write(directory / f"process-{operation}.json", dict(pid=child.pid, operation=operation,
                                                      started_ns=time.monotonic_ns()))
    return child


async def controller_child(directory, operation):
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.core.config import get_settings
    from app.modules.autonomy.experimental.authority import CurrentAuthority
    from app.modules.autonomy.experimental.comparators import ComparatorAdapter
    from app.modules.autonomy.experimental.controller import ExperimentalController
    from app.modules.autonomy.experimental.live_adapters import LiveModelAdapter
    from app.modules.autonomy.experimental.ports import Ports
    from app.modules.autonomy.experimental.schemas import ExperimentalPolicy
    from app.modules.autonomy.experimental.simulation import ConfiguredSimulator
    from app.modules.autonomy.live_settings import LiveSettings
    from app.modules.autonomy.registry import LiveRegistry

    config = read(directory / "child-config.json")
    policy = ExperimentalPolicy.model_validate(read(directory / "operator-policy.json"))
    settings = get_settings()
    engine = create_async_engine(settings.POSTGRES_DSN)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    owner = OwnedReceiver(directory, {}, config["case"])
    owner.cid, owner.owner = config["container_id"], config["owner"]
    owner.receiver_policy = read(directory / "receiver-policy.json")
    adapter = campaign_adapter_class()(policy=policy, receiver_policy=owner.receiver_policy,
        receiver_policy_sha256=config["receiver_policy_sha256"], token_path=directory / "receiver-token",
        transport=owner.exchange)
    registry = LiveRegistry(LiveSettings(str(directory / "registry.json"), config["registry_sha256"],
        config["model_root"], str(ai_interpreter()), str(directory / "observations")))
    model = (LiveModelAdapter(registry, redis, policy, equivalence_path=directory / "wrapper-equivalence.json")
             if policy.policy_kind == "model" else ComparatorAdapter(policy))
    transport = CampaignTransport(adapter, owner)
    captured = CapturedPorts(Ports(transport, model, ConfiguredSimulator(), transport), directory,
                            config["registry_sha256"], directory / "observations")
    controller = ExperimentalController(sessions, CurrentAuthority(sessions, redis),
        Ports(captured, captured, captured, captured), policy)
    outcome = dict(status="failed", operation=operation)
    try:
        if operation == "run":
            if policy.policy_kind == "model":
                from app.modules.autonomy.model_provider import _QUALIFICATION_TASKS
                await model.provider.qualify(CHECKPOINT)
                if _QUALIFICATION_TASKS:
                    await asyncio.gather(*list(_QUALIFICATION_TASKS))
                if not (await model.provider.qualify(CHECKPOINT)).qualified:
                    raise ValueError("child_qualification_unavailable")
                model._equivalence()
            from app.modules.autonomy.experimental.schemas import BootstrapCommand, BootstrapReceipt, contract_digest
            command = BootstrapCommand.model_validate(read(directory / "bootstrap-command.json"))

            async def reset(command, checkpoint):
                owner.checkpoint = checkpoint
                await checkpoint()
                owner.publish("bootstrap-admission.json", dict(policy_sha256=config["receiver_policy_sha256"],
                    request_id=str(command.request_id), expires_at=time.time() + 60, authorized=True))
                task = asyncio.create_task(owner.request("bootstrap", request_id=command.request_id))
                try:
                    while not task.done():
                        done, _ = await asyncio.wait({task}, timeout=.2)
                        if not done:
                            await checkpoint()
                    evidence = await task
                except BaseException:
                    await owner.request("stop")
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    raise
                write(directory / "bootstrap.json", evidence)
                owner.publish("controller-binding.json", dict(receiver_policy_sha256=config["receiver_policy_sha256"],
                    controller_policy_sha256=contract_digest(policy), run_id=evidence["episode_id"],
                    baseline_sha256=command.baseline_sha256))
                await owner.request("bind")
                # Adapter's local identity is its immutable installed policy. Bind
                # authentic episode separately for read-only snapshot validation;
                # retain original policy hash used by the receiver/core.
                adapter.measurement_run_id = uuid.UUID(evidence["episode_id"])
                return BootstrapReceipt(request_id=command.request_id, command_sha256=contract_digest(command),
                    measurement_run_id=evidence["episode_id"], runtime=policy.runtime,
                    registry_sha256=policy.registry_sha256, checkpoint_sha256=policy.checkpoint_sha256,
                    weights_sha256=policy.weights_sha256, model_source_sha256=policy.model_source_sha256,
                    baseline_sha256=command.baseline_sha256, ownership_sha256=command.ownership_sha256,
                    evidence=evidence)
            await controller.bootstrap(command, reset)
            await controller.run(admitted_bootstrap=True)
        else:
            await controller.recover()
        outcome["status"] = "completed"
    except Exception as exc:
        outcome["error_type"] = type(exc).__name__
        outcome["exception"] = exception_evidence(exc, directory)
        if str(exc) == "experimental_action_expired" and operation == "run":
            # Expected finite hold termination is accepted only with durable keep
            # and completed recovery, never merely because an exception was raised.
            from sqlalchemy import select
            from app.modules.autonomy.experimental.models import LabRun, LabReceipt
            async with sessions() as db:
                run = await db.get(LabRun, policy.run_id)
                phases = set((await db.scalars(select(LabReceipt.kind).where(LabReceipt.run_id == policy.run_id))).all())
            if run is not None and run.released and {"holding", "restored", "bootstrap_restored"} <= phases:
                outcome.update(status="completed", termination="verified_hold_expired_and_restored")
    finally:
        await adapter.close()
        # Normal recovery is the controller's job. Predispatch failure still owns
        # bootstrap routes; independently reconcile them through the sole receiver.
        try:
            await owner.request("status")
            bootstrap_cleanup = await owner.request("recover")
            write(directory / f"child-bootstrap-cleanup-{operation}.json", bootstrap_cleanup)
        except Exception as exc:
            outcome.update(status="failed", bootstrap_cleanup_error=type(exc).__name__)
        write(directory / ("controller-result.json" if operation == "run" else "recovery-result.json"),
              outcome | {"records": captured.records, "timings": captured.timings})
        await redis.aclose()
        await engine.dispose()
    return outcome


async def wait_file(path, timeout=60):
    async with asyncio.timeout(timeout):
        while not path.exists():
            await asyncio.sleep(.05)
    return read(path)


async def intervene(case, directory, receiver, child, sessions, redis, policy, plan):
    """Actual operator interventions at receiver-persisted one-shot boundaries."""
    from app.modules.autonomy.experimental.authority import CurrentAuthority
    from app.modules.autonomy.experimental.controller import ExperimentalController
    from sqlalchemy import text
    fault = case["fault"]
    if fault == "delayed-data":
        ready = await wait_file(directory / "observation-ready.json")
        await asyncio.sleep(plan["max_observation_age_seconds"] + 1)
        write(directory / "intervention.json", dict(**case, observation_ready=ready,
            applied_ns=time.monotonic_ns(), delay_seconds=plan["max_observation_age_seconds"] + 1))
        write(directory / "observation-release.json", {"released": True})
        return
    await wait_file(directory / "execute-ready.json")
    point = dict(policy_sha256=digest(directory / "receiver-policy.json"), operation="execute",
        ordinal=1, when="before" if case["phase"] == "beforewrite" else "after",
        effect="raise" if fault == "partial-apply" else "pause", timeout_seconds=30)
    receiver.publish("failpoint.json", point)
    write(directory / "execute-release.json", {"released": True})
    async with asyncio.timeout(45):
        while True:
            try:
                boundary = await asyncio.to_thread(receiver.receiver_file, "boundary.json")
                break
            except Exception:
                if child.returncode is not None:
                    raise ValueError("fault_boundary_not_reached")
                await asyncio.sleep(.1)
    event = dict(**case, boundary=boundary, applied_ns=time.monotonic_ns())
    if fault.startswith("STOP"):
        control = ExperimentalController(sessions, CurrentAuthority(sessions, redis), None, policy)
        event["core_stop"] = await control.stop()
        await receiver.request("status")
        event["receiver_stop"] = await receiver.request("stop")
    elif fault.startswith("revoke"):
        async with sessions() as db:
            await db.execute(text("UPDATE org_members SET org_role='Viewer' WHERE user_id=:actor"),
                             {"actor": uuid.UUID(policy.actor_id)})
            await db.commit()
        try:
            await CurrentAuthority(sessions, redis).check(policy)
        except Exception:
            event["current_authority_denied"] = True
        else:
            raise ValueError("real_revocation_not_effective")
        await asyncio.sleep(.5)
    elif fault in ("disconnect", "restart"):
        # SIGSTOP is an actual loss of all heartbeat/IPC progress, independent of
        # exception handling. Restart separately exercises immediate SIGKILL.
        if fault == "disconnect":
            import signal
            os.kill(child.pid, signal.SIGSTOP)
            await asyncio.sleep(receiver.receiver_policy["heartbeat_seconds"] + 1)
            event["disconnected_seconds"] = receiver.receiver_policy["heartbeat_seconds"] + 1
        child.kill()
        await child.wait()
        event.update(killed_pid=child.pid, returncode=child.returncode)
        await asyncio.sleep(receiver.receiver_policy["heartbeat_seconds"] + 1)
    elif fault == "link-failure":
        event["link_down"] = await asyncio.to_thread(receiver.link_state, case, "down")
    elif fault == "ambiguous-receipt":
        # Exact deterministic write has occurred; drop the execute response in the
        # controller transport, never alter the receiver's native receipt.
        write(directory / "drop-execute-response.json", {"request_id": boundary["entry"].get("request_id")})
    elif fault != "partial-apply":
        raise ValueError("undeclared_fault")
    if fault != "partial-apply":
        receiver.publish("release.json", {"boundary_sha256": boundary["id"], "release": True})
    if fault == "link-failure":
        # Preserve the actual outage interval, then restore this owned intervention
        # so the receiver can independently verify original forwarding recovery.
        await asyncio.sleep(5)
        event["link_up"] = await asyncio.to_thread(receiver.link_state, case, "up")
    write(directory / "intervention.json", event)


def contract_readiness():
    """No import-triggered acquisition and no made-up fault/baseline dispatch API."""
    from app.modules.autonomy.experimental.adapter import ExperimentalLabAdapter
    from app.modules.autonomy.experimental.controller import ExperimentalController
    from app.modules.autonomy.experimental.simulation import ConfiguredSimulator
    from app.modules.autonomy.experimental.comparators import ComparatorAdapter
    from emulation.experimental_lab_receiver import Receiver
    from app.core.schema_version import CURRENT_SCHEMA

    return dict(core=all(hasattr(ExperimentalController, key) for key in ("run", "stop", "recover")),
                adapter=all(hasattr(ExperimentalLabAdapter, key) for key in
                            ("observe", "prepare", "execute", "verify", "recover")),
                simulator=hasattr(ConfiguredSimulator, "simulate"),
                deterministic_mutation_fault_contract=hasattr(Receiver, "boundary"),
                durable_bootstrap_recovery=hasattr(CampaignTransport, "recover_bootstrap"),
                retention_schema_0029=CURRENT_SCHEMA=="0029" and bool(list((ROOT/"backend/alembic/versions").glob("0029_*.py"))),
                matched_baseline_controller_contract=hasattr(ComparatorAdapter, "infer"))


def lab_preflight(output):
    """Inspect existing containers only; preserve shared services and deny other labs."""
    from scripts.acceptance.runtime import docker
    identities = docker("ps", "-q", "--no-trunc").split()
    rows = []
    for identity in identities:
        row = json.loads(docker("inspect", "--format",
            '{"id":{{json .Id}},"name":{{json .Name}},"privileged":{{json .HostConfig.Privileged}},'
            '"image":{{json .Image}}}', identity))
        if row["privileged"] or any(word in row["name"] for word in ("nanfo-training", "nanfo-experimental", "native-driver")):
            raise ValueError("another_running_lab_prevents_launch")
        rows.append(row)
    write(output / "preflight-existing-containers.json", rows)


class OwnedReceiver:
    """One exact-ID disconnected container; operator helper provides bounded IPC."""

    def __init__(self, directory, plan, case):
        self.directory, self.plan, self.case = directory, plan, case
        self.cid = self.volume = None
        self.owner = uuid.uuid4().hex
        self.receiver_policy = None
        self.fence = 0
        self.checkpoint = None

    def docker(self, *args, timeout=60):
        # Reuse existing bounded recording-free Docker utility; never log secret argv.
        from scripts.acceptance.runtime import docker
        return docker(*args, timeout=timeout).strip()

    def allocate(self):
        from emulation.experimental_lab_contract import IMAGE
        self.volume = "nanfo-experimental-" + self.owner
        self.docker("volume", "create", "--label", "nanfo.adr025.owner=" + self.owner, self.volume)
        self.cid = self.docker("create", "--pull=never", "--name", self.volume,
            "--label", "nanfo.adr025.owner=" + self.owner, "--network", "none", "--privileged",
            "--cpus", "2", "--memory", "768m", "--memory-swap", "768m", "--pids-limit", "256",
            "--mount", "type=volume,src=" + self.volume + ",dst=/run/nanfo-experimental",
            "--tmpfs", "/run:exec,size=64m", "--tmpfs", "/tmp:exec,size=64m",
            "--env", "NANFO_LAB_IMAGE_ID=" + IMAGE, "--entrypoint", "/usr/bin/tini",
            IMAGE, "--", "sleep", "3600")
        self.docker("start", self.cid)
        self.docker("exec", self.cid, "chmod", "700", "/run/nanfo-experimental")
        write(self.directory / "container.json", dict(container_id=self.cid, image_id=IMAGE,
              owner=self.owner, network="none", wrapper_separate=True))
        return self.cid

    def start(self, projection):
        import secrets
        self.receiver_policy = projection
        receiver_pin = write(self.directory / "receiver-policy.json", projection)
        token = self.directory / "receiver-token"
        fd = os.open(token, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(secrets.token_hex(32))
        write(self.directory / "campaign-admission.json", dict(policy_sha256=receiver_pin,
              admitted=True, container_id=self.cid))
        for name in ("receiver-policy.json", "receiver-token", "campaign-admission.json"):
            self.copy_private(self.directory / name, "/run/nanfo-experimental/" + name)
        self.docker("exec", self.cid, "mkdir", "-m", "700", "/run/nanfo-wrapper")
        for path in sorted(ROOT.glob("emulation/experimental_lab*.py")):
            self.copy_wrapper(path)
        self.copy_wrapper(Path(__file__))
        self.publish("campaign-setup.json", dict(receiver_policy_sha256=receiver_pin,
            initial_action=self.case.get("bootstrap_initial_action", 0), campaign_source_sha256=digest(Path(__file__))))
        launcher = ("import subprocess,sys; f=open('/run/nanfo-experimental/receiver-diagnostic.log','wb'); "
                    "p=subprocess.Popen(['python','-B','/run/nanfo-wrapper/verify_experimental_lab.py',"
                    "'receiver','--output','/run/nanfo-experimental','--receiver-policy-sha256',sys.argv[1]],stdout=f,stderr=f); "
                    "raise SystemExit(p.wait())")
        self.docker("exec", "-d", self.cid, "python", "-c", launcher, receiver_pin)
        return receiver_pin, token

    def copy_wrapper(self, path):
        """Docker archive cp cannot see /run tmpfs; fixed stdin write sees live mount."""
        self.copy_private(path, "/run/nanfo-wrapper/"+path.name)

    def copy_private(self, path, destination):
        if (not destination.startswith(("/run/nanfo-wrapper/", "/run/nanfo-experimental/"))
                or "/../" in destination):
            raise ValueError("receiver_copy_scope_invalid")
        content = path.read_bytes()
        pin = hashlib.sha256(content).hexdigest()
        code = ("import os,sys,hashlib; p=sys.argv[1]; data=sys.stdin.buffer.read(1048577); "
                "assert len(data)<=1048576 and hashlib.sha256(data).hexdigest()==sys.argv[2]; "
                "fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600); "
                "f=os.fdopen(fd,'wb'); f.write(data); f.flush(); os.fsync(f.fileno()); f.close()")
        subprocess.run(["docker","exec","-i",self.cid,"python","-c",code,
            destination,pin], input=content, capture_output=True, check=True, timeout=15)

    def publish(self, name, value):
        path = self.directory / name
        write(path, value)
        self.copy_private(path, "/run/nanfo-experimental/" + name)

    def receiver_file(self, name):
        # Fixed names only; native receiver files are root-owned inside the container.
        if name not in {"boundary.json", "journal.json", "checkpoint-request.json", "campaign-authority.json"}:
            raise ValueError("receiver_read_not_allowlisted")
        code = ("from pathlib import Path; import sys; p=Path(sys.argv[1]); "
                "assert p.stat().st_size<=16777216; sys.stdout.buffer.write(p.read_bytes())")
        result = subprocess.run(["docker", "exec", self.cid, "python", "-c", code,
            "/run/nanfo-experimental/" + name], capture_output=True, check=True, timeout=10)
        if len(result.stdout) > 16 * 1024**2:
            raise ValueError("native_journal_size_limit")
        return json.loads(result.stdout)

    async def request(self, operation, *, request_id=None):
        from emulation.experimental_lab_contract import canonical, VERSION
        self.fence += 1
        request = dict(version=VERSION, request_id=str(request_id or uuid.uuid4()), fence=self.fence,
            policy_sha256=digest(self.directory / "receiver-policy.json"), expires_at=time.time() + 60,
            operation=operation, action=None, duration_seconds=0,
            token=(self.directory / "receiver-token").read_text())
        response = await self.exchange(canonical(request))
        if response.get("status") != "ok":
            raise ValueError("receiver_operator_request_failed")
        if operation == "status":
            self.fence = max(self.fence, response["evidence"]["current_fence"])
        return response["evidence"]

    async def ready(self):
        async with asyncio.timeout(90):
            while True:
                try:
                    value = await self.request("status")
                    if "baseline" not in value:
                        raise ValueError("receiver_baseline_not_ready")
                    return value
                except (ValueError, subprocess.SubprocessError):
                    await asyncio.sleep(.5)

    async def exchange(self, payload):
        from emulation.experimental_lab_operator import exchange
        request = json.loads(payload)
        task = asyncio.create_task(asyncio.to_thread(exchange, self.receiver_policy, payload))
        bridge = (asyncio.create_task(self.checkpoint_bridge(request["request_id"]))
                  if request["operation"] in ("bootstrap", "execute", "verify") and self.checkpoint else None)
        try:
            response = await task
        finally:
            if bridge:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        if request["operation"] not in ("status", "heartbeat"):
            path = self.directory / ("wire-" + request["request_id"] + ".json")
            if path.exists():
                raise ValueError("operator_execute_request_replayed")
            write(path, dict(request={k: v for k, v in request.items() if k != "token"}, response=response))
        if request["operation"] == "execute" and (self.directory / "drop-execute-response.json").exists():
            write(self.directory / "lost-native-receipt.json", response)
            raise TimeoutError("injected_response_loss_after_native_receipt")
        return response

    async def checkpoint_bridge(self, request_id):
        """One attached bounded relay per operation; each add still calls real core."""
        code = """import sys,time,json
from pathlib import Path
sys.path.insert(0,'/run/nanfo-wrapper')
from experimental_lab_contract import atomic_write,protected_read
path=Path('/run/nanfo-experimental/checkpoint-request.json')
deadline=time.monotonic()+65
last=None
while time.monotonic()<deadline:
 if path.exists():
  value=json.loads(protected_read(path))
  if value['request_id']==sys.argv[1] and value['id']!=last:
   print(json.dumps(value),flush=True)
   line=sys.stdin.buffer.readline(8193)
   if not line: break
   response=json.loads(line)
   assert response['id']==value['id']
   atomic_write('/run/nanfo-experimental/checkpoint-response.json',response)
   last=value['id']
 time.sleep(.02)
"""
        process = await asyncio.create_subprocess_exec("docker","exec","-i",self.cid,"python","-u","-c",code,request_id,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            async with asyncio.timeout(65):
                while line := await process.stdout.readline():
                    challenge = json.loads(line)
                    allowed = True
                    try:
                        await self.checkpoint()
                    except Exception:
                        allowed = False
                    value = {"id":challenge["id"],"authorized":allowed}
                    process.stdin.write(json.dumps(value).encode()+b"\n")
                    await process.stdin.drain()
                    write(self.directory / ("authority-check-"+value["id"]+".json"),
                          value | {"completed_monotonic_ns":time.monotonic_ns()})
        finally:
            process.stdin.close()
            if process.returncode is None:
                process.terminate()
            await process.wait()

    def checkpoint_reply(self, value):
        code = ("import sys; sys.path.insert(0,'/run/nanfo-wrapper'); "
                "from experimental_lab_contract import atomic_write,decode; "
                "atomic_write('/run/nanfo-experimental/checkpoint-response.json',decode(sys.stdin.buffer.read()))")
        subprocess.run(["docker","exec","-i",self.cid,"python","-c",code],
            input=json.dumps(value).encode(), capture_output=True, check=True, timeout=5)
        write(self.directory / ("authority-check-" + value["id"] + ".json"),
              value | {"completed_monotonic_ns":time.monotonic_ns()})

    def link_state(self, case, state):
        if state not in ("up", "down"):
            raise ValueError("invalid_link_intervention")
        identity = self.receiver_file("journal.json")["runtime"]["namespace_identities"]["access1"]
        interface = "access1-eth" + ("2" if case["scenario"] == "path0" else "1")
        # Native namespace identity was recorded by the sole receiver; validate its
        # PID start clock before the fixed link command. No route/rule commands here.
        code = ("import json,os,sys,subprocess; from pathlib import Path; "
                "i=json.loads(sys.argv[1]); p=i['pid']; s=Path('/proc/%s/stat'%p).read_text(); "
                "assert int(s[s.rfind(')')+2:].split()[19])==i['start_ticks']; "
                "assert os.readlink('/proc/%s/ns/net'%p)==i['netns']; "
                "r=subprocess.run(['nsenter','-t',str(p),'-n','--','ip','link','set','dev',sys.argv[2],sys.argv[3]],"
                "capture_output=True,text=True,timeout=5); "
                "b=subprocess.run(['nsenter','-t',str(p),'-n','--','ip','-j','link','show','dev',sys.argv[2]],capture_output=True,text=True,timeout=5); "
                "print(json.dumps({'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr,'readback':json.loads(b.stdout)})); "
                "sys.exit(r.returncode)")
        started = time.monotonic_ns()
        value = json.loads(self.docker("exec", self.cid, "python", "-c", code,
                                      json.dumps(identity), interface, state))
        return value | dict(node="access1", interface=interface, state=state,
                            started_ns=started, finished_ns=time.monotonic_ns(), identity=identity)

    def close(self):
        removed, unresolved, evidence_errors = [], [], []
        try:
            if self.cid:
                info = json.loads(self.docker("inspect", "--format",
                    '{"id":{{json .Id}},"owner":{{json (index .Config.Labels "nanfo.adr025.owner")}}}', self.cid))
                if info != {"id": self.cid, "owner": self.owner}:
                    raise ValueError("receiver_cleanup_owner_mismatch")
                try:
                    journal = self.receiver_file("journal.json")
                    write(self.directory / "native-journal.json", journal)
                    write(self.directory / "campaign-authority.json", self.receiver_file("campaign-authority.json"))
                    self.export_frames(journal)
                except Exception as exc:
                    evidence_errors.append(type(exc).__name__)
                    # Private diagnostic only; never part of portable/public evidence.
                    try:
                        self.docker("cp", self.cid+":/run/nanfo-experimental/receiver-diagnostic.log",
                                    str(self.directory / "receiver-diagnostic.private.log"))
                    except Exception:
                        pass
                self.docker("stop", "--time", "20", self.cid, timeout=30)
                self.docker("rm", self.cid)
                removed.append(self.cid)
            if self.volume:
                owner = self.docker("volume", "inspect", "--format", '{{index .Labels "nanfo.adr025.owner"}}', self.volume)
                if owner != self.owner:
                    raise ValueError("receiver_volume_owner_mismatch")
                self.docker("volume", "rm", self.volume)
                removed.append(self.volume)
        except Exception:
            unresolved = [value for value in (self.cid, self.volume) if value and value not in removed]
        value = dict(removed=not unresolved, removed_resources=removed, unresolved_resources=unresolved,
                     evidence_errors=evidence_errors)
        write(self.directory / "cleanup.json", value)
        return value

    def export_frames(self, journal):
        """Copy every receiver-persisted frame, including rejected/partial windows."""
        pins = journal["runtime"]["frame_hashes"]
        if len(pins)>16 or len(set(pins))!=len(pins):
            raise ValueError("native_frame_inventory_invalid")
        frames = self.directory/"raw-frames"
        frames.mkdir(mode=0o700)
        inventory=[]
        for pin in pins:
            if len(pin)!=64 or any(c not in "0123456789abcdef" for c in pin):
                raise ValueError("native_frame_hash_invalid")
            code = ("from pathlib import Path; import sys; p=Path('/run/nanfo-experimental')/('frame-'+sys.argv[1]+'.json'); "
                    "assert p.stat().st_size<=2097152; sys.stdout.buffer.write(p.read_bytes())")
            content=subprocess.run(["docker","exec",self.cid,"python","-c",code,pin],
                capture_output=True,check=True,timeout=10).stdout
            from scripts.audit_experimental_lab import canonical
            if canonical(json.loads(content))!=pin:
                raise ValueError("native_frame_bytes_changed")
            target=frames/(pin+".json")
            with target.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            inventory.append(dict(path="raw-frames/"+target.name,sha256=digest(target),canonical_sha256=pin))
        write(self.directory/"raw-frame-inventory.json",inventory)


async def joined_case(directory, plan, case, sessions, redis, actor):
    """Concrete positive composition through the owners' ports; no live mocks."""
    from datetime import UTC, datetime, timedelta
    from app.modules.autonomy.experimental.schemas import ExperimentalPolicy
    from app.modules.autonomy.experimental.simulation import evaluator_sha256
    from app.modules.autonomy.live_settings import LiveSettings
    from app.modules.autonomy.model_provider import _QUALIFICATION_TASKS
    from app.modules.autonomy.registry import LiveRegistry
    from app.modules.autonomy.schemas import contract_digest
    from scripts.frozen_model_diagnostic import canonical_hash
    from emulation.experimental_lab_contract import IMAGE, SOURCE, wrapper_digest

    directory.mkdir(mode=0o700)
    receiver = OwnedReceiver(directory, plan, case)
    result = dict(case_id=case["case_id"], status="failed", policy=case["policy"],
                  seed=case["seed"], scenario=case["scenario"])
    try:
        cid = await asyncio.to_thread(receiver.allocate)
        now = datetime.now(UTC)
        observations = directory / "observations"
        observations.mkdir(mode=0o700)
        template = read(Path(plan["model"]["root"]) / "live-registry.template.json")
        template.update(installed_at=(now - timedelta(seconds=1)).isoformat(),
            expires_at=(now + timedelta(seconds=plan["case_budget_seconds"] + 180)).isoformat(),
            scopes=[dict(network_id=actor["network_id"], workspace_id=actor["workspace_id"],
                         snapshot_path="snapshot.json")])
        registry_pin = write(directory / "registry.json", template)
        registry = LiveRegistry(LiveSettings(str(directory / "registry.json"), registry_pin,
            plan["model"]["root"], str(ai_interpreter()), str(observations)))
        limits = plan["thresholds"]
        # Qualification runs before acquisition so its full raw reconstruction does
        # not age the first observation. Every comparator shares the same registry.
        from app.modules.autonomy.model_provider import FrozenModelProvider
        qualifier = FrozenModelProvider(registry, redis)
        await qualifier.qualify(CHECKPOINT)
        if _QUALIFICATION_TASKS:
            await asyncio.gather(*list(_QUALIFICATION_TASKS))
        qualification = await qualifier.qualify(CHECKPOINT)
        write(directory / "qualification.json", qualification.model_dump(mode="json"))
        if not qualification.qualified:
            raise ValueError("qualified_frozen_runtime_unavailable")
        from emulation.experimental_lab_contract import POLICY_VERSION
        projection = dict(version=POLICY_VERSION, image_id=IMAGE, source_sha256=SOURCE,
            model_sha256=CHECKPOINT, container_id=cid, owner_label=receiver.owner,
            seed=case["seed"], scenario=case["scenario"], expires_at=time.time() + 300,
            max_duration_seconds=plan["max_action_seconds"], heartbeat_seconds=10,
            min_dwell_seconds=plan["minimum_dwell_seconds"], max_observation_age_seconds=30,
            min_goodput_mbps=limits["min_goodput_mbps"], max_loss_fraction=limits["max_udp_loss_fraction"],
            max_rtt_ms=limits["max_probe_rtt_ms"], wrapper_sha256=wrapper_digest(),
            controller_policy_sha256=None)
        validate_native_projection(projection)
        receiver_hash, _ = await asyncio.to_thread(receiver.start, projection)
        baseline = await receiver.ready()
        write(directory / "baseline-capture.json", baseline)
        now = datetime.now(UTC)
        from app.modules.autonomy.experimental import live_adapters
        runtime = dict(resource_id=cid, container_id=cid, image_sha256=IMAGE.removeprefix("sha256:"),
            source_sha256=SOURCE, wrapper_sha256=wrapper_digest(), disposable=True, network_disconnected=True)
        equivalence = live_adapters.WrapperEquivalence(runtime=runtime, registry_sha256=registry_pin,
            checkpoint_sha256=CHECKPOINT, weights_sha256=plan["model"]["weights_sha256"],
            model_source_sha256=canonical_hash(template["source_sha256"]),
            model_adapter_sha256=digest(Path(live_adapters.__file__)),
            evidence_sha256=[plan["offline_gates_sha256"]],
            scope="offline original matched argv equivalence and preserved raw-frame interface replay; fresh inference still fully validated")
        equivalence_pin = write(directory / "wrapper-equivalence.json", equivalence.model_dump(mode="json"))
        policy = ExperimentalPolicy(version="nanfo.experimental-lab/v1", run_id=uuid.uuid4(),
            policy_kind="model" if case["policy"] == "qualified" else case["policy"],
            wrapper_equivalence_sha256=equivalence_pin if case["policy"] == "qualified" else None,
            model_adapter_sha256=equivalence.model_adapter_sha256 if case["policy"] == "qualified" else None,
            actor_id=actor["actor_id"], network_id=actor["network_id"], workspace_id=actor["workspace_id"],
            runtime=runtime,
            registry_sha256=registry_pin, checkpoint_sha256=CHECKPOINT, weights_sha256=plan["model"]["weights_sha256"],
            model_source_sha256=canonical_hash(template["source_sha256"]),
            preregistration_sha256=digest(directory.parent / "plan.json"), evaluator_sha256=evaluator_sha256(),
            routes=[dict(action_id=f"route{i}", device_ids=["access1", f"dist{i+1}", "access2"],
                         path=["access1", f"dist{i+1}", "access2"]) for i in (0, 1)],
            assumptions=plan["simulation"]["assumptions"], objectives=plan["simulation"]["objectives"],
            verification=dict(min_goodput_mbps=limits["min_goodput_mbps"],
                max_loss_fraction=limits["max_udp_loss_fraction"], max_probe_loss_fraction=limits["max_probe_loss_fraction"],
                max_rtt_ms=limits["max_probe_rtt_ms"],
                min_probe_sent=limits["min_probe_sent"], min_traffic_bytes=limits["min_traffic_bytes"]),
            max_observation_age_seconds=plan["max_observation_age_seconds"],
            min_dwell_seconds=plan["minimum_dwell_seconds"], max_actions=1,
            action_window_seconds=60, max_actions_per_window=1,
            max_action_duration_seconds=plan["max_action_seconds"], lease_seconds=plan["lease_seconds"],
            io_timeout_seconds=plan["io_timeout_seconds"], poll_seconds=1, starts_at=now - timedelta(seconds=1),
            expires_at=now + timedelta(seconds=plan["case_budget_seconds"] + 180))
        write(directory / "operator-policy.json", policy.model_dump(mode="json"))
        from app.modules.autonomy.experimental.schemas import BootstrapCommand, contract_digest
        bootstrap_command = BootstrapCommand(request_id=uuid.uuid4(), run_id=policy.run_id,
            runtime=policy.runtime, policy_sha256=contract_digest(policy), receiver_policy_sha256=receiver_hash,
            baseline=baseline["baseline"], baseline_sha256=baseline["baseline_sha256"],
            ownership_sha256=contract_digest({"runtime":runtime, "receiver_policy_sha256":receiver_hash}))
        write(directory / "bootstrap-command.json", bootstrap_command.model_dump(mode="json"))
        # The controller is an actual separate process; restart never means a new
        # in-process fixture instance. Private service environment is inherited.
        write(directory / "child-config.json", dict(model_root=plan["model"]["root"],
            registry_sha256=registry_pin, receiver_policy_sha256=receiver_hash,
            actor=actor, case=case, owner=receiver.owner, container_id=cid))
        write(directory / "auth.json", actor)
        if "fault" in case:
            write(directory / "fault-case.json", case)
        child = await start_controller_child(directory, "run")
        try:
            async with asyncio.timeout(plan["case_budget_seconds"]):
                if "fault" in case:
                    await intervene(case, directory, receiver, child, sessions, redis, policy, plan)
                await child.wait()
                if case.get("fault") in ("restart", "disconnect"):
                    await asyncio.sleep(plan["lease_seconds"] + 1)
                    recovery_child = await start_controller_child(directory, "recover")
                    try:
                        async with asyncio.timeout(75):
                            await recovery_child.wait()
                    finally:
                        if recovery_child.returncode is None:
                            recovery_child.kill()
                            await recovery_child.wait()
                    if recovery_child.returncode:
                        raise ValueError("restart_recovery_child_failed")
        finally:
            if child.returncode is None:
                child.kill()
                await child.wait()
        await export_journal(sessions, policy.run_id, directory / "journal.json")
        outcome = read(directory / "controller-result.json") if (directory / "controller-result.json").exists() else {}
        result.update(status="acquired", controller_returncode=child.returncode,
                      controller_status=outcome.get("status","unavailable"))
    except (Exception, asyncio.CancelledError) as exc:
        import traceback
        result.update(error_type=type(exc).__name__, locations=[dict(file=Path(f.filename).name, line=f.lineno)
            for f in traceback.extract_tb(exc.__traceback__)])
        if isinstance(exc, ValueError) and str(exc).replace("_", "").isalnum():
            result["reason"] = str(exc)
        result["exception"] = exception_evidence(exc, directory)
    finally:
        try:
            if (directory / "operator-policy.json").exists() and not (directory / "journal.json").exists():
                await export_journal(sessions, policy.run_id, directory / "journal.json")
            if receiver.receiver_policy:
                await receiver.request("status")
                restored = await receiver.request("recover")
                write(directory / "operator-recovery.json", restored)
        except Exception as exc:
            result.update(status="failed", export_error_type=type(exc).__name__)
        finally:
            result["cleanup"] = await asyncio.to_thread(receiver.close)
            if not result["cleanup"]["removed"]:
                result["status"] = "failed"
            write(directory / "attempt.json", result)
    return result


def reference(root, path):
    return dict(path=str(path.relative_to(root)), sha256=digest(path))


def assemble_case(root, case, attempt):
    """References point to actual retained returns; no synthetic success receipts."""
    directory = root / case["case_id"]
    row = {**case, "status": attempt["status"], "outcome": "unavailable"}
    for key, filename in (("auth", "auth.json"), ("operator_policy", "operator-policy.json"),
                          ("journal", "journal.json"), ("native_journal", "native-journal.json"),
                          ("bootstrap", "bootstrap.json"), ("intervention", "intervention.json"),
                          ("native_authority", "campaign-authority.json"),
                          ("raw_frames", "raw-frame-inventory.json"),
                          ("cleanup", "cleanup.json"), ("controller", "controller-result.json"),
                          ("recovery_process", "recovery-result.json")):
        path = directory / filename
        if path.exists():
            row[key] = reference(root, path)
    row["chain"] = {}
    for filename in ("controller-result.json", "recovery-result.json"):
        if (directory / filename).exists():
            record = read(directory / filename)
            for kind, ref in record["records"].items():
                row["chain"][kind] = {**ref, "path": case["case_id"] + "/" + ref["path"]}
    if "journal" in row:
        journal = read(directory / "journal.json")
        run = journal.get("run")
        phases = [r["kind"] for r in journal["receipts"]]
        if run and run["released"] and run["phase"] == "restored":
            row["outcome"] = "restored" if "dispatching" in phases else "predispatch_rejected"
        # Recover exported receipt even when an interrupted child could not publish its result.
        for kind, phase in (("frame", "observed"), ("inference", "inferred"), ("simulation", "simulated"),
                            ("prepared", "prepared"), ("receipt", "verifying"),
                            ("verification", "verified"), ("recovery", "restored")):
            values = [r["payload"] for r in journal["receipts"] if r["kind"] == phase]
            if values:
                path = directory / f"exported-{kind}.json"
                write(path, values[-1])
                row["chain"][kind] = reference(root, path)
    if "native_journal" in row:
        native = read(directory / "native-journal.json")
        for key, value in (("native_commands", native["runtime"]["transcript"]),
                           ("boundary_events", native["boundary_events"])):
            path = directory / (key + ".json")
            write(path, value)
            row[key] = reference(root, path)
    if read(root/"plan.json").get("outcome_protocol") == OUTCOME_PROTOCOL and "fault" not in case:
        from scripts.audit_experimental_lab import classify_nominal
        try:
            classification=classify_nominal(root,row)
            row.update(outcome=classification["outcome"], status="completed" if classification["protocol_complete"] else "failed")
            write(directory/"outcome-audit.json",classification)
            row["outcome_audit"]=reference(root,directory/"outcome-audit.json")
        except Exception as exc:
            row.update(status="failed",outcome="unproven",outcome_error=type(exc).__name__+":"+str(exc))
    elif attempt["status"]=="acquired":
        row["status"]="completed" if case.get("fault") or attempt.get("controller_status")=="completed" else "failed"
    return row


async def dispatch_matrix(output, plan, sessions, redis, deadline):
    """Ordered finite scheduler, retaining every case including unexecuted suffix."""
    rows, errors = [], []
    for case in plan["trials"] + plan["faults"]:
        if (time.monotonic() + plan["case_budget_seconds"] + plan.get("bootstrap_budget_seconds", 90)
                + plan["cleanup_reserve_seconds"] > deadline):
            row = {**case, "status": "not_run", "reason": "finite_campaign_budget_exhausted"}
        else:
            directory = output / case["case_id"]
            try:
                if source_pins() != plan["source_sha256"]:
                    raise ValueError("campaign_source_changed_before_case")
                actor = await provision_actor(sessions, redis)
                async with asyncio.timeout(plan["case_budget_seconds"] + plan.get("bootstrap_budget_seconds", 90)):
                    attempt = await joined_case(directory, plan, case, sessions, redis, actor)
                row = assemble_case(output, case, attempt)
            except Exception as exc:
                errors.append(dict(case_id=case["case_id"], error_type=type(exc).__name__,
                                   exception=exception_evidence(exc,directory)))
                row = {**case, "status": "failed", "reason": "case_or_export_failed"}
            if (directory / "cleanup.json").exists() and not read(directory / "cleanup.json")["removed"]:
                deadline = 0  # unresolved ownership forbids successor acquisition
        rows.append(row)
        write(output / ("case-result-" + case["case_id"] + ".json"), row)
    return rows, errors


def validate_plan(output):
    plan = read(output / "plan.json")
    if plan["version"] != VERSION or plan["training"] is not False or plan["calibrated"] is not False:
        raise ValueError("invalid_experimental_plan")
    if digest(output / "seed-audit.json") != plan["seed_audit_sha256"]:
        raise ValueError("seed_audit_changed")
    audit = read(output / "seed-audit.json")
    seeds = {item["seed"] for item in plan["trials"] + plan["faults"] + plan.get("smoke", [])}
    if seeds & set(audit["reserved_seeds"]) or any(not 1000 <= s < 2000 for s in seeds):
        raise ValueError("nonfresh_operational_seed")
    if model_identity(Path(plan["model"]["root"])) != plan["model"]:
        raise ValueError("model_identity_changed")
    if plan.get("runtime_snapshot_sha256"):
        verify_runtime_snapshot()
        if digest(ROOT/"frozen-runtime.json")!=plan["runtime_snapshot_sha256"]:
            raise ValueError("runtime_snapshot_changed")
    if source_pins() != plan["source_sha256"]:
        raise ValueError("implementation_changed_since_preregistration")
    for relative, pin in plan["source_sha256"].items():
        if digest(output / "source" / relative) != pin:
            raise ValueError("archived_campaign_source_changed")
    return plan


def admission(output, path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
        raise ValueError("parent_admission_must_be_private_owned_regular_file")
    value = read(path)
    if (value.get("version") != "nanfo.experimental-parent-admission/v1"
            or value.get("core_adapter_ready") is not True
            or value.get("authorize_privileged_launch") is not True
            or value.get("plan_sha256") != digest(output / "plan.json")
            or not time.time_ns() < value.get("expires_ns", 0)):
        raise ValueError("parent_launch_not_admitted")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "check", "launch", "child", "gates", "receiver", "freeze"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--pairs", type=int, default=6)
    parser.add_argument("--budget-seconds", type=int, default=7200)
    parser.add_argument("--parent-admission", type=Path)
    parser.add_argument("--gate-evidence", type=Path)
    parser.add_argument("--child-operation", choices=("run", "recover"))
    parser.add_argument("--receiver-policy-sha256")
    args = parser.parse_args()
    os.umask(0o077)
    if args.operation == "freeze":
        print(json.dumps(freeze_runtime(args.output),sort_keys=True))
        return 0
    if args.operation == "receiver":
        return receiver_main(str(args.output), args.receiver_policy_sha256)
    if args.operation == "gates":
        result = offline_gates(args.output)
    elif args.operation == "child":
        key = os.environ.pop("NANFO_EXPERIMENTAL_CHILD", "")
        if (not args.child_operation or not key or
                read(args.output / f"child-admission-{args.child_operation}.json")["key_sha256"]
                != hashlib.sha256(key.encode()).hexdigest()):
            parser.error("child is private campaign process entrypoint")
        result = asyncio.run(controller_child(args.output, args.child_operation))
    elif args.operation == "prepare":
        with campaign_slot():
            prepare(args.output, model=args.model, pairs=args.pairs, budget_seconds=args.budget_seconds,
                    gate_evidence=args.gate_evidence)
        result = dict(status="prepared", plan_sha256=digest(args.output / "plan.json"))
    elif args.operation == "check":
        validate_plan(args.output)
        readiness = contract_readiness()
        result = dict(status="prepared-not-launched" if all(readiness.values()) else "blocked",
                      readiness=readiness, plan_sha256=digest(args.output / "plan.json"), privileged_launch=False)
    else:
        if args.parent_admission is None:
            parser.error("launch requires --parent-admission issued after core/adapter readiness")
        with campaign_slot():
            validate_plan(args.output)
            admission(args.output, args.parent_admission)
            result = asyncio.run(launch(args.output))
    displayed = ({"status": result["status"], "output": str(args.output),
                  "checks": [{"argv": row["argv"], "returncode": row["returncode"]} for row in result["checks"]]}
                 if args.operation == "gates" else result)
    print(json.dumps(displayed, sort_keys=True))
    return 0 if result["status"] in {"prepared", "prepared-not-launched", "passed", "completed"} else 1


async def launch(output):
    """One complete finite matrix; any unavailable/failed/missed case is non-success."""
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.core.config import get_settings
    from scripts.audit_experimental_lab import audit
    verify_runtime_snapshot()
    plan = validate_plan(output)
    if plan.get("runtime_snapshot_sha256") != digest(ROOT/"frozen-runtime.json"):
        raise ValueError("plan_runtime_snapshot_unbound")
    if not plan.get("offline_gates_sha256") or digest(output / "offline-gates.json") != plan["offline_gates_sha256"]:
        raise ValueError("launch_requires_preregistered_offline_gates")
    readiness = contract_readiness()
    if not all(readiness.values()):
        result = dict(status="blocked", readiness=readiness, privileged_launch=False,
                      calibrated=False, reason="complete_joined_campaign_contract_not_ready")
        write(output / "launch-blocked.json", result)
        return result
    reject_new_seed_reservations(output, plan)
    lab_preflight(output)
    write(output / "launch-started.json", dict(plan_sha256=digest(output / "plan.json"),
                                              started_ns=time.time_ns(), readiness=readiness))
    deadline = time.monotonic() + plan["budget_seconds"]
    with private_services(output):
        settings = get_settings()
        engine = create_async_engine(settings.POSTGRES_DSN)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            smoke_rows, errors = await dispatch_matrix(output, {**plan, "trials":plan["smoke"], "faults":[]},
                                                       sessions, redis, deadline)
            from scripts.audit_experimental_lab import audit_smoke
            try:
                smoke_result = audit_smoke(output, plan, smoke_rows)
            except Exception as exc:
                smoke_result = dict(status="failed", error_type=type(exc).__name__, reason=str(exc))
            write(output / "smoke-result.json", smoke_result)
            if smoke_result["status"] == "passed":
                rows, matrix_errors = await dispatch_matrix(output, plan, sessions, redis, deadline)
                errors.extend(matrix_errors)
            else:
                rows = [{**case,"status":"not_run","reason":"preregistered_smoke_failed"}
                        for case in plan["trials"]+plan["faults"]]
        finally:
            await redis.aclose()
            await engine.dispose()
    cleanup_rows = [read(path) for path in output.glob("*/cleanup.json")]
    service_cleanup = read(output / "private-services-cleanup.json")
    unresolved = [r for row in cleanup_rows for r in row["unresolved_resources"]]
    if not service_cleanup["children_reaped"] or not service_cleanup["private_tree_removed"]:
        unresolved.append("private-services")
    write(output / "cleanup.json", dict(removed=not unresolved, unresolved_resources=unresolved,
                                       private_services=service_cleanup))
    manifest = dict(plan_sha256=digest(output / "plan.json"), cases=rows,
        status="completed" if all(r["status"] == "completed" for r in rows) else "incomplete",
        auth_mode="real-private-postgres-redis", provider_mocks=False, errors=errors,
        smoke=smoke_rows, smoke_result=reference(output, output / "smoke-result.json"),
        cleanup=reference(output, output / "cleanup.json"))
    write(output / "campaign-evidence.json", manifest)
    try:
        result = audit(output)
    except Exception as exc:
        result = dict(status="failed", error_type=type(exc).__name__, reason=str(exc), calibrated=False)
    write(output / "result.json", result)
    return result


def offline_gates(output):
    """Executable source/test admission; no Docker run, service startup or traffic."""
    output.mkdir(mode=0o700, exist_ok=False)
    before = source_pins()
    review = (ROOT/"backend/tests/frozen_independent_review.py" if (ROOT/"frozen-runtime.json").exists()
              else Path("/tmp/opencode/test_adr025_integrated_review.py"))
    commands = [
        [sys.executable, "-m", "pytest", "tests/unit/test_experimental_campaign.py",
         "tests/unit/test_experimental_lab.py", "tests/unit/test_experimental_lab_adapter.py",
         "tests/unit/test_experimental_simulation.py", "--no-cov", "-q"],
        [sys.executable, "-m", "ruff", "check", "--isolated", "scripts/verify_experimental_lab.py",
         "scripts/audit_experimental_lab.py", "tests/unit/test_experimental_campaign.py"],
        [sys.executable, "-m", "unittest", "emulation.tests.test_experimental_lab", "-q"],
        [sys.executable, "-m", "pytest", str(review),
         "-k", "test_stop_during_final_current_authority_read_is_not_admitted or test_bootstrap_stop_during_admission_read_is_not_admitted",
         "--no-cov", "-q"],
    ]
    results = []
    for index, command in enumerate(commands):
        result = subprocess.run(command, cwd=ROOT if index == 2 else ROOT / "backend",
                                capture_output=True, timeout=180, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                                    "PYTHONPATH":str(ROOT / "backend")+os.pathsep+str(ROOT)})
        results.append(dict(argv=command, returncode=result.returncode,
                            stdout=result.stdout.decode(), stderr=result.stderr.decode()))
    pins = source_pins()
    value = dict(status="passed" if before == pins and all(r["returncode"] == 0 for r in results) else "failed",
                 sources_unchanged_during_checks=before == pins,
                 source_sha256=pins, checks=results, privileged_launch=False,
                 scope="offline fixtures and actual preserved frozen-source equivalence; not fresh traffic")
    write(output / "offline-gates.json", value)
    return value


if __name__ == "__main__":
    sys.exit(main())
