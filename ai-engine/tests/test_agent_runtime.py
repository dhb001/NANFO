"""ADR022 software acceptance with real shadow schemas; no model or lab artifacts."""

import ast
import hashlib
import json
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from copy import deepcopy
from pathlib import Path

import pytest

# Reuse the existing validated shadow fixture factory, not a new inference schema.
from test_shadow import NOW, SCOPE, writeBundle
from test_shadow import bundle as shadow_bundle

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from agent_runtime import scheduler  # noqa: E402
from agent_runtime.contracts import (  # noqa: E402
    AgentOutcome,
    AgentRegistration,
    MemoryItem,
    Registry,
    Request,
    RuntimeDecision,
    Scope,
)
from agent_runtime.memory import Memory  # noqa: E402
from agent_runtime.registry import authorize  # noqa: E402
from agent_runtime.runtime import EvidenceFiles, analyze, runOnce  # noqa: E402
from shadow.schemas import Finding  # noqa: E402

sys.path.remove(str(SCRIPTS))
NOW_UNIX = NOW.timestamp()
PIN = "a" * 64


@pytest.fixture
def bundle():
    return shadow_bundle.__wrapped__()


@pytest.fixture
def setup(tmp_path, bundle):
    scope = Scope(
        tenant_id=SCOPE["workspace_id"],
        network_id=SCOPE["network_id"],
        model_sha256=bundle[0]["model"]["policy_sha256"],
        trace_id="trace-1",
    )
    request = Request(version=1, scope=scope, session_id="session-1", run_id="run-1")
    registry = Registry(
        version=1,
        operator_id="operator-1",
        expires_unix=NOW_UNIX + 600,
        scopes=[scope],
        permissions=["analyze", "run", "memory_read", "memory_write", "export"],
        agents=[
            AgentRegistration(agent_id=name, scopes=[scope], tools=[tool])
            for name, tool in (
                ("capacity", "read_observation"),
                ("failure", "read_observation"),
                ("policy", "read_review_policy"),
            )
        ],
    )
    args = writeBundle(tmp_path, bundle)
    args.pop("now")
    evidence = EvidenceFiles(**args)
    return registry, request, evidence


@pytest.fixture
def store(tmp_path):
    value = Memory(tmp_path / "memory.sqlite")
    yield value
    value.close()


def changed(value, **updates):
    return type(value).model_validate(value.model_dump() | updates)


def item(request, *, tier="short_term", memory_id="memory-1", ttl=100.0):
    return MemoryItem(
        memory_id=memory_id,
        scope=request.scope,
        session_id=request.session_id,
        tier=tier,
        kind="graph_reference"
        if tier == "semantic"
        else "incident"
        if tier == "long_term"
        else "observation_note",
        summary="Recorded congestion; inspect original source.",
        provenance_sha256=[PIN],
        source_reference="diagnostic:fixture-record",
        source_observed_unix=NOW_UNIX - 20,
        source_expires_unix=NOW_UNIX + 200,
        created_unix=NOW_UNIX,
        ttl_seconds=ttl,
        graph_references=["node-a", "link-a-b"] if tier == "semantic" else [],
    )


def test_registry_only_allows_builtin_read_tools_and_exact_permissions(setup):
    registry, request, _ = setup
    for patch in ({"agent_id": "llm"}, {"tools": ["execute"]}, {"module": "evil.plugin"}):
        with pytest.raises(ValueError):
            changed(registry.agents[0], **patch)
    with pytest.raises(ValueError, match="duplicate registered agent"):
        changed(registry, agents=[registry.agents[0], registry.agents[0]])
    authorize(registry, request.scope, "analyze", NOW_UNIX)
    with pytest.raises(PermissionError):
        authorize(registry, request.scope, "execute", NOW_UNIX)
    with pytest.raises(PermissionError):
        authorize(registry, request.scope, "analyze", registry.expires_unix)


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", "ffffffff-ffff-ffff-ffff-ffffffffffff"),
        ("network_id", "ffffffff-ffff-ffff-ffff-ffffffffffff"),
        ("model_sha256", "f" * 64),
        ("trace_id", "other-trace"),
    ],
)
def test_memory_cannot_cross_any_scope_component(store, setup, field, value):
    registry, request, _ = setup
    store.ingest(registry, request, item(request), NOW_UNIX)
    other = changed(request, scope=changed(request.scope, **{field: value}))
    with pytest.raises(PermissionError):
        store.retrieve(registry, other, NOW_UNIX)
    # Even an operator explicitly authorized for both scopes cannot retrieve the
    # first tenant/model/trace's records through the second scope's SQL lookup.
    broader = changed(registry, scopes=[request.scope, other.scope])
    assert store.retrieve(broader, other, NOW_UNIX) == []
    with pytest.raises(PermissionError):
        store.ingest(broader, other, item(request), NOW_UNIX)


@pytest.mark.parametrize("tier", ["working", "short_term", "long_term", "semantic"])
def test_memory_tier_ttl_source_expiry_and_session(store, setup, tier):
    registry, request, _ = setup
    memory = item(request, tier=tier)
    store.ingest(registry, request, memory, NOW_UNIX)
    assert store.retrieve(registry, request, NOW_UNIX + 99) == [memory]
    assert store.retrieve(registry, request, NOW_UNIX + 100) == []
    other_session = changed(request, session_id="another-session")
    assert bool(store.retrieve(registry, other_session, NOW_UNIX)) == (tier != "working")
    expired_source = changed(memory, memory_id="source-2", source_expires_unix=NOW_UNIX + 10)
    store.ingest(registry, request, expired_source, NOW_UNIX)
    assert len(store.retrieve(registry, request, NOW_UNIX + 9)) == 2
    assert store.retrieve(registry, request, NOW_UNIX + 10) == [memory]


def test_memory_retrieval_bounds_order_and_semantic_refs(store, setup):
    registry, request, _ = setup
    for index in reversed(range(8)):
        store.ingest(
            registry, request, item(request, tier="semantic", memory_id=f"m-{index}"), NOW_UNIX
        )
    selected = store.retrieve(
        registry, changed(request, retrieval_limit=3, tiers=["semantic"]), NOW_UNIX
    )
    assert [row.memory_id for row in selected] == ["m-0", "m-1", "m-2"]
    assert selected[0].graph_references == ["node-a", "link-a-b"]
    with pytest.raises(ValueError):
        changed(request, retrieval_limit=51)
    with pytest.raises(ValueError):
        changed(item(request, tier="semantic"), graph_references=[])
    with pytest.raises(ValueError):
        changed(item(request, tier="working"), ttl_seconds=3601.0)


def test_memory_denials_immutability_and_audit(store, setup):
    registry, request, _ = setup
    denied = changed(registry, permissions=["analyze"])
    with pytest.raises(PermissionError):
        store.ingest(denied, request, item(request), NOW_UNIX)
    with pytest.raises(ValueError, match="expired_or_future"):
        store.ingest(registry, request, item(request), NOW_UNIX - 1)
    store.ingest(registry, request, item(request), NOW_UNIX)
    with pytest.raises(sqlite3.IntegrityError):
        store.ingest(registry, request, item(request), NOW_UNIX)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store.db.execute("UPDATE memory SET body='{}'")
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store.db.execute("DELETE FROM audit")
    audit = store.audit(registry, request, NOW_UNIX)
    assert len(audit) == 1 and audit[0]["record"]["kind"] == "memory_ingested"
    store.retrieve(registry, request, NOW_UNIX)
    later = store.audit(registry, request, NOW_UNIX, after=audit[-1]["sequence"])
    assert later[0]["record"]["previous"] == audit[-1]["sha256"]


def test_memory_content_tamper_and_capacity_fail_closed(store, setup, monkeypatch):
    registry, request, _ = setup
    store.ingest(registry, request, item(request), NOW_UNIX)
    store.db.execute("DROP TRIGGER memory_update_deny")  # simulate operator-file tampering
    store.db.execute("UPDATE memory SET body='{}'")
    with pytest.raises(ValueError, match="tampered"):
        store.retrieve(registry, request, NOW_UNIX)
    import agent_runtime.memory as memory_module

    monkeypatch.setattr(memory_module, "MAX_ROWS", 1)
    with pytest.raises(ValueError, match="capacity"):
        store.ingest(registry, request, item(request, memory_id="another"), NOW_UNIX)


def test_sqlite_private_file_and_schema_version(tmp_path):
    path = tmp_path / "public.sqlite"
    path.touch(mode=0o644)
    with pytest.raises(ValueError, match="not_private"):
        Memory(path)
    link = tmp_path / "symlink.sqlite"
    link.symlink_to(path)
    with pytest.raises(OSError):
        Memory(link)
    private = tmp_path / "private.sqlite"
    memory = Memory(private)
    assert private.stat().st_mode & 0o777 == 0o600
    memory.db.execute("PRAGMA user_version=99")
    memory.close()
    with pytest.raises(ValueError, match="schema_incompatible"):
        Memory(private)


@pytest.mark.parametrize("clock", [float("nan"), float("inf"), -1.0])
def test_invalid_clock_cannot_bypass_expiry(setup, clock):
    registry, request, _ = setup
    with pytest.raises(ValueError, match="invalid_clock"):
        authorize(registry, request.scope, "analyze", clock)


def test_runtime_checks_shadow_scope_even_when_operator_registry_allows_it(setup):
    registry, request, evidence = setup
    other = changed(request.scope, tenant_id="ffffffff-ffff-ffff-ffff-ffffffffffff")
    registry = changed(registry, scopes=[request.scope, other])
    with pytest.raises(PermissionError, match="shadow_scope"):
        analyze(registry, changed(request, scope=other), evidence, PIN, clock=lambda: NOW_UNIX)


def test_agent_scope_denial_is_not_overridden_by_operator_scope(setup):
    registry, request, evidence = setup
    other = changed(request.scope, trace_id="trace-other")
    registry = changed(
        registry,
        scopes=[request.scope, other],
        agents=[changed(registry.agents[0], scopes=[other]), *registry.agents[1:]],
    )
    result = analyze(registry, request, evidence, PIN, clock=lambda: NOW_UNIX)
    assert result.agents[0].state == "denied"
    assert result.consensus.posture == "abstain"


def test_checkpoint_write_rechecks_revoked_permissions(store, setup):
    registry, request, _ = setup
    generation = store.claim(registry, request, PIN, NOW_UNIX)
    revoked = changed(registry, permissions=["memory_read"])
    with pytest.raises(PermissionError):
        store.checkpoint(revoked, request, generation, "capacity", {}, NOW_UNIX)
    assert store.checkpoints(registry, request, NOW_UNIX) == {}


def test_completed_decision_and_audit_cannot_be_exported_cross_scope(store, setup):
    registry, request, evidence = setup
    runOnce(store, registry, request, evidence, PIN, clock=lambda: NOW_UNIX)
    other = changed(request.scope, trace_id="unrelated")
    other_request = changed(request, scope=other)
    broader = changed(registry, scopes=[request.scope, other])
    with pytest.raises(ValueError, match="not_found"):
        store.export(broader, other_request, NOW_UNIX)
    assert store.audit(broader, other_request, NOW_UNIX) == []


def test_scheduler_timeout_error_and_permission_are_explicit(setup, monkeypatch):
    registry, request, evidence = setup
    plan, diagnostic, _ = evidence.load(NOW_UNIX)
    agent = changed(registry.agents[0], timeout_seconds=0.01)
    previous = signal.getsignal(signal.SIGALRM)
    monkeypatch.setattr(scheduler, "invoke", lambda *args: time.sleep(0.2))
    start = time.monotonic()
    assert scheduler.schedule(agent, request.scope, plan, diagnostic, 1).state == "timeout"
    assert time.monotonic() - start < 0.15
    assert signal.getsignal(signal.SIGALRM) == previous
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)

    def broken(*args):
        raise RuntimeError("secret internal text")

    monkeypatch.setattr(scheduler, "invoke", broken)
    result = scheduler.schedule(agent, request.scope, plan, diagnostic, 1)
    assert result.state == "error" and "secret" not in result.model_dump_json()
    agent = changed(agent, tools=["read_review_policy"])
    assert scheduler.schedule(agent, request.scope, plan, diagnostic, 1).state == "denied"
    assert (
        scheduler.schedule(registry.agents[0], request.scope, plan, diagnostic, 0).state
        == "timeout"
    )


def test_coordination_is_deterministic_preserves_dissent_and_options(setup):
    registry, request, evidence = setup
    first = analyze(registry, request, evidence, PIN, clock=lambda: NOW_UNIX)
    reversed_registry = changed(registry, agents=list(reversed(registry.agents)))
    second = analyze(reversed_registry, request, evidence, PIN, clock=lambda: NOW_UNIX)
    assert first == second
    assert first.consensus.posture == "review"
    assert first.consensus.review_weight == 6 and first.consensus.observe_weight == 1
    assert [row.agent_id for row in first.consensus.dissent] == ["policy"]
    assert {row.option for row in first.consensus.alternatives} >= {
        "ospf",
        "constant0",
        "constant1",
        "heuristic",
        "hold_and_review",
        "investigate_flagged_evidence",
    }
    assert first.consensus.safety_confidence is None and not first.safety_authorized


def test_consensus_minority_warning_tie_and_missing_agents(setup):
    _, _, evidence = setup
    _, _, shadow = evidence.load(NOW_UNIX)
    rows = [
        AgentOutcome(
            agent_id=name,
            state="completed",
            evidence_weight=weight,
            reason="fixture_evidence",
            finding=Finding(
                agent=name,
                status=status,
                rationale="Measured finding",
                evidence_references=["diagnostic:fixture"],
                assumptions=["No calibration"],
            ),
        )
        for name, status, weight in (
            ("capacity", "observed", 4),
            ("failure", "review", 2),
            ("policy", "observed", 1),
        )
    ]
    result = scheduler.consensus(rows, shadow)
    assert result.posture == "observe" and result.dissent == [rows[1]]
    assert "investigate_flagged_evidence" in [alt.option for alt in result.alternatives]
    rows[0] = changed(rows[0], evidence_weight=1)
    assert scheduler.consensus(rows, shadow).posture == "review"  # tie: 2 vs 2
    assert scheduler.consensus(rows[:2], shadow).posture == "abstain"


def test_run_persists_checkpoints_reflection_and_exact_replay(store, setup):
    registry, request, evidence = setup
    store.ingest(registry, request, item(request), NOW_UNIX)
    result = runOnce(store, registry, request, evidence, PIN, clock=lambda: NOW_UNIX)
    assert result.memory_ids == ["memory-1"] and len(result.memory_sha256) == 1
    assert result.workflow[-2:] == ["execute:unavailable", "reflect:record_review_without_learning"]
    audit_before = store.audit(registry, request, NOW_UNIX)
    assert runOnce(store, registry, request, evidence, PIN, clock=lambda: NOW_UNIX + 1) == result
    assert store.audit(registry, request, NOW_UNIX) == audit_before
    assert store.export(registry, request, NOW_UNIX) == result
    memory = store.retrieve(registry, request, NOW_UNIX)
    reflection = next(row for row in memory if row.kind == "reflection")
    assert reflection.source_expires_unix == NOW_UNIX + 50  # oldest outcome age=70, max=120
    assert set(store.checkpoints(registry, request, NOW_UNIX)) == {
        "memory",
        "capacity",
        "failure",
        "policy",
    }
    with pytest.raises(ValueError, match="identity_conflict"):
        runOnce(
            store,
            registry,
            changed(request, session_id="other"),
            evidence,
            PIN,
            clock=lambda: NOW_UNIX,
        )


def test_restart_resumes_only_missing_agents_and_drops_expired_memory(tmp_path, setup, monkeypatch):
    registry, request, evidence = setup
    path = tmp_path / "recovery.sqlite"
    first = Memory(path)
    first.ingest(registry, request, item(request, ttl=10.0), NOW_UNIX)
    original_checkpoint = first.checkpoint

    def interrupted(*args, **kwargs):
        original_checkpoint(*args, **kwargs)
        if args[3] == "capacity":
            raise KeyboardInterrupt("simulated process interruption")

    monkeypatch.setattr(first, "checkpoint", interrupted)
    with pytest.raises(KeyboardInterrupt):
        runOnce(first, registry, request, evidence, PIN, clock=lambda: NOW_UNIX)
    first.close()
    second = Memory(path)
    try:
        with pytest.raises(ValueError, match="lease_busy"):
            runOnce(second, registry, request, evidence, PIN, clock=lambda: NOW_UNIX + 29)
        original = scheduler.invoke
        calls = []

        def counted(agent, *args):
            calls.append(agent.agent_id)
            return original(agent, *args)

        monkeypatch.setattr(scheduler, "invoke", counted)
        result = runOnce(second, registry, request, evidence, PIN, clock=lambda: NOW_UNIX + 31)
        assert calls == ["failure", "policy"]
        assert result.memory_ids == []
        assert "run_recovered" in [
            row["record"]["kind"] for row in second.audit(registry, request, NOW_UNIX + 31)
        ]
        assert result.consensus.posture == "review"
    finally:
        second.close()


def test_lease_generation_fences_previous_owner(store, setup):
    registry, request, _ = setup
    old = store.claim(registry, request, PIN, NOW_UNIX)
    new = store.claim(registry, request, PIN, NOW_UNIX + 30)
    assert (old, new) == (1, 2)
    with pytest.raises(ValueError, match="fence_lost"):
        store.checkpoint(registry, request, old, "capacity", {}, NOW_UNIX + 31)


def test_expired_shadow_or_denied_agent_never_produces_dispatch(store, setup):
    registry, request, evidence = setup
    denied = changed(
        registry,
        agents=[changed(registry.agents[0], tools=["read_review_policy"]), *registry.agents[1:]],
    )
    result = runOnce(store, denied, request, evidence, PIN, clock=lambda: NOW_UNIX + 120)
    assert result.shadow.status == result.consensus.posture == "abstain"
    assert result.agents[0].state == "denied"
    assert result.execution == "not_applied" and not result.production_dispatch
    assert store.retrieve(registry, request, NOW_UNIX + 120) == []  # stale reflection not refreshed


def test_future_evidence_is_archived_without_reflection(store, setup):
    registry, request, evidence = setup
    result = runOnce(store, registry, request, evidence, PIN, clock=lambda: NOW_UNIX - 80)
    assert result.shadow.freshness.status == "future"
    assert result.consensus.posture == "abstain"
    assert store.retrieve(registry, request, NOW_UNIX - 80) == []
    assert store.export(registry, request, NOW_UNIX - 80) == result


def test_no_dispatch_network_training_or_dynamic_plugins(store, setup, monkeypatch):
    registry, request, evidence = setup

    def denied(*args, **kwargs):
        raise AssertionError("forbidden side effect")

    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(subprocess, "Popen", denied)
    original_import = __import__

    def guarded(name, *args, **kwargs):
        if name.startswith(("torch", "nanfo_routing", "gymnasium", "langgraph", "app.")):
            denied()
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", guarded)
    result = runOnce(store, registry, request, evidence, PIN, clock=lambda: NOW_UNIX)
    assert not result.online_learning and not result.safety_authorized
    forbidden = {
        "subprocess",
        "socket",
        "torch",
        "nanfo_routing",
        "gymnasium",
        "importlib",
        "langgraph",
    }
    for path in (SCRIPTS / "agent_runtime").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                assert not {alias.name.split(".")[0] for alias in node.names} & forbidden
            if isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in forbidden


def test_runtime_cli_clean_checkout_all_commands_and_restart(tmp_path, bundle, setup):
    registry, request, evidence = setup
    root = tmp_path / "clean"
    root.mkdir()
    for package in ("agent_runtime", "shadow"):
        shutil.copytree(
            SCRIPTS / package, root / package, ignore=shutil.ignore_patterns("__pycache__")
        )
    # Shift the synthetic timeline to current UTC for the CLI's real clock.
    delta = time.time() - NOW_UNIX
    fresh = deepcopy(bundle)
    from datetime import UTC, datetime

    for field in ("frozen_at", "selected_at", "observation_at"):
        fresh[0][field] = datetime.fromtimestamp(
            datetime.fromisoformat(fresh[0][field]).timestamp() + delta, UTC
        ).isoformat()
    fresh[1]["created_at"] = datetime.fromtimestamp(NOW_UNIX - 10 + delta, UTC).isoformat()
    for row in fresh[2]["rows"]:
        for field in ("measured_start", "measured_end"):
            row[field] = datetime.fromtimestamp(
                datetime.fromisoformat(row[field]).timestamp() + delta, UTC
            ).isoformat()
    inputs = tmp_path / "cli-inputs"
    inputs.mkdir()
    files = writeBundle(inputs, fresh)
    registry = changed(registry, expires_unix=time.time() + 600)
    registry_path = inputs / "registry.json"
    registry_path.write_text(registry.model_dump_json())
    request_path = inputs / "request.json"

    def call(command, selected=request):
        request_path.write_text(selected.model_dump_json())
        args = [
            sys.executable,
            "-B",
            "-m",
            "agent_runtime",
            command,
            "--registry",
            str(registry_path),
            "--registry-sha256",
            hashlib.sha256(registry_path.read_bytes()).hexdigest(),
            "--request",
            str(request_path),
            "--request-sha256",
            hashlib.sha256(request_path.read_bytes()).hexdigest(),
            "--database",
            str(tmp_path / "cli.sqlite"),
        ]
        if command in ("analyze", "run-once"):
            args.extend(
                [
                    "--plan",
                    str(files["plan_path"]),
                    "--plan-sha256",
                    files["plan_sha256"],
                    "--diagnostic",
                    str(files["diagnostic_path"]),
                    "--outcomes",
                    str(files["outcomes_path"]),
                    "--benchmark",
                    str(files["benchmark_path"]),
                ]
            )
        result = subprocess.run(
            args,
            cwd=root,
            env={"PATH": os.defpath, "LANG": "C.UTF-8"},
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert not result.stderr
        return json.loads(result.stdout)

    entry = item(request)
    entry = changed(
        entry,
        created_unix=entry.created_unix + delta,
        source_observed_unix=entry.source_observed_unix + delta,
        source_expires_unix=entry.source_expires_unix + delta,
    )
    assert call("ingest", changed(request, item=entry))["status"] == "ingested"
    assert call("retrieve")["items"][0]["memory_id"] == entry.memory_id
    assert call("analyze")["execution"] == "not_applied"
    result = call("run-once")
    assert RuntimeDecision.model_validate_json(json.dumps(result)).memory_ids == [entry.memory_id]
    assert call("run-once") == result  # fresh process restart, immutable replay
    assert call("export") == result
    assert call("audit")["events"][-1]["record"]["kind"] == "run_completed"
