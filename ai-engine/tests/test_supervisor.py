"""Offline supervision tests. No Docker, measured campaign, or generated fallback."""

import json
import os
import signal
import subprocess
from types import SimpleNamespace

import pytest

from nanfo_routing import cli
from nanfo_routing import supervisor as s
from nanfo_routing.contracts import jsonBytes
from nanfo_routing.transport import DockerTransport

IMAGE = "sha256:" + "a" * 64
CAMPAIGN = "b" * 32
CID = "c" * 64


@pytest.fixture
def supervisor(tmp_path):
    frozen = {**s.plan(IMAGE), "campaign_id": CAMPAIGN, "output": str(tmp_path)}
    return s.Supervisor(tmp_path, frozen)


def test_frozen_plan_seeds_and_no_test():
    plan = s.plan(IMAGE)
    assert plan == s.plan(IMAGE)
    assert plan["config"]["budget_seconds"] == 7200
    assert plan["config"]["cleanup_reserve_seconds"] == 120
    assert [row["scenario"] for row in plan["calibration"]] == ["path0", "path1"]
    assert len({row["scenario"] for row in plan["validation"]}) == 6
    training = [row["seed"] for block in plan["training"] for row in block]
    assert training == list(range(1200, 1296))
    assert {row["seed"] for row in plan["validation"]} == set(range(2200, 2206))
    assert plan["test"] == "not accessed" and not plan["automatic_campaign_resume"]
    with pytest.raises(ValueError):
        s.plan("nanfo-emulation:latest")


@pytest.mark.parametrize(
    "rewards,transitions,baseline,reason",
    [
        ([0.1, 0.1], 96, 0.5, None),
        ([0.1, 0.1, 0.1], 143, 0.5, None),
        ([0.1, 0.1, 0.1], 144, 0.5, "low_quality_no_advantage_over_constant"),
        ([0.5, 0.4, 0.3], 144, 0.1, None),
        ([0.5, 0.4, 0.3, 0.2], 192, 0.1, "validation_plateau"),
        ([0.5, 0.51, 0.515, 0.519], 192, 0.1, "validation_plateau"),
        ([0.5, 0.51, 0.53, 0.54], 192, 0.1, None),
        ([0.1, 0.2, 0.3], 144, 0.1, None),
    ],
)
def test_early_stop(rewards, transitions, baseline, reason):
    assert s.earlyStop(rewards, transitions, baseline) == reason


@pytest.mark.parametrize("rewards", [[], [float("nan")], [float("inf")]])
def test_invalid_reward_stops(rewards):
    with pytest.raises(ValueError):
        s.earlyStop(rewards, 144, 0.1)


def calibration():
    return {
        policy: {
            "episodes": [
                {"seed": 1001, "scenario": "path0", "reward": a},
                {"seed": 1002, "scenario": "path1", "reward": b},
            ]
        }
        for policy, a, b in (("constant0", 0.0, 2.0), ("constant1", 2.0, 0.0))
    }


def test_learnability_requires_both_actual_return_signs():
    summaries = calibration()
    assert s.learnability(summaries) == {"path0": 0.5, "path1": 0.5}
    summaries["constant0"]["episodes"][1]["reward"] = 0.0
    with pytest.raises(ValueError, match="learnability preflight failed"):
        s.learnability(summaries)
    summaries = calibration()
    summaries["constant1"]["episodes"][0]["scenario"] = "overload"
    with pytest.raises(ValueError, match="scenario/seed"):
        s.learnability(summaries)


def owner(supervisor):
    record = {
        "campaign_id": CAMPAIGN,
        "name": "nanfo-training-" + CAMPAIGN,
        "image_id": IMAGE,
        "cidfile": "train-01.cid",
    }
    (supervisor.output / "owner.json").write_bytes(jsonBytes(record))
    (supervisor.output / record["cidfile"]).write_text(CID)
    return record


def test_cleanup_exact_id_and_label_only(supervisor, monkeypatch):
    record = owner(supervisor)
    calls = []
    responses = iter(
        [
            CID,
            json.dumps(
                {
                    "Id": CID,
                    "Name": "/" + record["name"],
                    "Image": IMAGE,
                    "Config": {"Labels": {s.LABEL: CAMPAIGN}},
                }
            ),
            CID,
            "",
        ]
    )

    def command(argv, *args, **kwargs):
        calls.append(argv)
        return next(responses)

    monkeypatch.setattr(supervisor, "command", command)
    supervisor.cleanup()
    assert calls[2] == ["docker", "stop", "--time", "20", CID]
    assert all("nanfo-experiment" not in argv for argv in calls)


@pytest.mark.parametrize("field", ["Id", "Name", "Image", "label"])
def test_cleanup_refuses_other_owners(supervisor, monkeypatch, field):
    record = owner(supervisor)
    details = {
        "Id": CID,
        "Name": "/" + record["name"],
        "Image": IMAGE,
        "Config": {"Labels": {s.LABEL: CAMPAIGN}},
    }
    if field == "label":
        details["Config"]["Labels"][s.LABEL] = "other"
    else:
        details[field] = "other"
    calls = []

    def command(argv, *args, **kwargs):
        calls.append(argv)
        return CID if argv[1] == "ps" else json.dumps(details)

    monkeypatch.setattr(supervisor, "command", command)
    with pytest.raises(ValueError, match="ownership mismatch"):
        supervisor.cleanup()
    assert not any("stop" in argv for argv in calls)


def test_cleanup_missing_id_never_uses_name(supervisor, monkeypatch):
    record = owner(supervisor)
    (supervisor.output / record["cidfile"]).unlink()
    monkeypatch.setattr(supervisor, "command", lambda *a, **k: pytest.fail("no ownership proof"))
    with pytest.raises(ValueError, match="no captured"):
        supervisor.cleanup()
    record["cidfile"] = "../other.cid"
    with pytest.raises(ValueError, match="ownership"):
        supervisor.containerId(record)


def test_cleanup_absent_is_idempotent(supervisor, monkeypatch):
    owner(supervisor)
    monkeypatch.setattr(supervisor, "command", lambda *a, **k: "")
    supervisor.cleanup()
    supervisor.cleanup()


@pytest.mark.parametrize("failedCommand", ["inspect", "stop"])
@pytest.mark.parametrize("recheck", ["absent", "present", "query-failed", "unexpected-id"])
def test_cleanup_auto_remove_race_requires_successful_absence_query(
    supervisor, monkeypatch, failedCommand, recheck
):
    record = owner(supervisor)
    supervisor.status["container_id"] = CID
    calls = []
    lookupCount = 0
    now = [supervisor.started]
    monkeypatch.setattr(s.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(s.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))

    def command(argv, *args, **kwargs):
        nonlocal lookupCount
        calls.append(argv)
        assert kwargs["cleanup"] is True
        if argv[1] == "ps":
            assert argv == [
                "docker",
                "ps",
                "-a",
                "--no-trunc",
                "--filter",
                f"id={CID}",
                "--format",
                "{{.ID}}",
            ]
            lookupCount += 1
            if lookupCount == 1:
                return CID
            if recheck == "query-failed":
                raise RuntimeError("Docker unavailable")
            return {"absent": "", "present": CID, "unexpected-id": "d" * 64}[recheck]
        assert argv[-1] == CID
        if argv[1] == failedCommand:
            raise RuntimeError("auto-remove raced with " + failedCommand)
        assert argv[1] == "inspect"
        return json.dumps(
            {
                "Id": CID,
                "Name": "/" + record["name"],
                "Image": IMAGE,
                "Config": {"Labels": {s.LABEL: CAMPAIGN}},
            }
        )

    monkeypatch.setattr(supervisor, "command", command)
    if recheck == "absent":
        supervisor.cleanup()
        assert supervisor.status["container_id"] is None
    else:
        with pytest.raises((RuntimeError, ValueError)):
            supervisor.cleanup()
        assert supervisor.status["container_id"] == CID
    assert lookupCount == (31 if recheck == "present" else 2)
    actions = ["ps", "inspect"] if failedCommand == "inspect" else ["ps", "inspect", "stop"]
    assert [argv[1] for argv in calls] == actions + ["ps"] * (lookupCount - 1)
    assert all(record["name"] not in argv and "nanfo-experiment" not in argv for argv in calls)


@pytest.mark.parametrize("failedCommand", [None, "inspect", "stop"])
@pytest.mark.parametrize("outcome", ["delayed-absent", "present", "mismatch", "query-failed"])
def test_cleanup_waits_for_async_removal_without_repeating_actions(
    supervisor, monkeypatch, failedCommand, outcome
):
    record = owner(supervisor)
    supervisor.status["container_id"] = CID
    now = [supervisor.started]
    beats, calls, queryTimes = [], [], []
    monkeypatch.setattr(s.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(s.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    monkeypatch.setattr(supervisor, "heartbeat", lambda: beats.append(now[0]))
    # Cleanup must work inside the reserve even with an operator stop pending.
    supervisor.workDeadline = now[0] - 1
    supervisor.requested = "operator_stop"

    def command(argv, timeout, **kwargs):
        calls.append(argv)
        assert kwargs == {"cleanup": True}
        if argv[1] == "ps":
            assert argv[argv.index("--filter") + 1] == f"id={CID}"
            queryTimes.append(now[0])
            if len(queryTimes) <= 3:
                return CID
            if outcome == "query-failed":
                raise RuntimeError("Docker query failed")
            return {"delayed-absent": "", "present": CID, "mismatch": "d" * 64}[outcome]
        assert argv[-1] == CID
        if argv[1] == failedCommand:
            raise RuntimeError("auto-removal raced")
        if argv[1] == "inspect":
            return json.dumps(
                {
                    "Id": CID,
                    "Name": "/" + record["name"],
                    "Image": IMAGE,
                    "Config": {"Labels": {s.LABEL: CAMPAIGN}},
                }
            )
        assert argv[1] == "stop"
        return CID

    monkeypatch.setattr(supervisor, "command", command)
    if outcome == "delayed-absent":
        supervisor.cleanup()
        assert supervisor.status["container_id"] is None
        assert now[0] - supervisor.started == pytest.approx(2)
    else:
        with pytest.raises((RuntimeError, ValueError), match="deadline|mismatch|query failed"):
            supervisor.cleanup()
        assert supervisor.status["container_id"] == CID
    assert beats and max(b - a for a, b in zip(beats, beats[1:], strict=False)) <= 2
    assert now[0] - supervisor.started <= 30
    assert [argv[1] for argv in calls if argv[1] != "ps"] == (
        ["inspect"] if failedCommand == "inspect" else ["inspect", "stop"]
    )


def test_cleanup_removal_wait_honors_hard_deadline(supervisor, monkeypatch):
    owner(supervisor)
    supervisor.status["container_id"] = CID
    now = [supervisor.started]
    supervisor.hardDeadline = now[0] + 2.5
    monkeypatch.setattr(s.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(s.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    queryTimeouts = []

    def command(argv, timeout, **kwargs):
        if argv[1] == "inspect":
            raise RuntimeError("owner is removing")
        assert argv[1] == "ps" and kwargs["cleanup"]
        queryTimeouts.append(timeout)
        return CID

    monkeypatch.setattr(supervisor, "command", command)
    with pytest.raises(RuntimeError, match="cleanup deadline"):
        supervisor.cleanup()
    assert now[0] == supervisor.hardDeadline
    assert queryTimeouts == [10, 2.5, 1.5, 0.5]
    assert supervisor.status["container_id"] == CID


@pytest.mark.parametrize("remaining", [800, 1499, 1500])
def test_round_admission_reserves_two_sessions_and_overhead(supervisor, monkeypatch, remaining):
    monkeypatch.setattr(supervisor, "exclusiveLab", lambda: None)
    monkeypatch.setattr(supervisor, "command", lambda *a, **k: IMAGE)
    monkeypatch.setattr(s.time, "monotonic", lambda: supervisor.workDeadline - remaining)
    monkeypatch.setattr(
        s,
        "report",
        lambda *a: {
            "matched_offered_schedules": True,
            "comparable_held_out_schedules": True,
        },
    )
    calls = []

    def session(stage, split, first, count, policy="ppo", checkpoint=None):
        calls.append(stage)
        if stage.startswith("calibration-"):
            return calibration()[policy]
        if stage.startswith("baseline-"):
            return {"decision_mean": 0.1}
        raise s.Stopped("offline test: round admitted")

    monkeypatch.setattr(supervisor, "session", session)
    assert s.plan(IMAGE)["config"]["round_admission_seconds"] == 1500
    assert supervisor.hardDeadline - supervisor.workDeadline == pytest.approx(120)
    assert supervisor.hardDeadline - supervisor.started == pytest.approx(7200)
    if remaining < 1500:
        assert supervisor.campaign() == "insufficient_budget_for_round"
        assert not any(stage.startswith("train-") for stage in calls)
    else:
        with pytest.raises(s.Stopped, match="round admitted"):
            supervisor.campaign()
        assert calls[-1] == "train-01"


@pytest.mark.parametrize(
    "name,labels,image",
    [
        ("nanfo-experiment", "", "unknown"),
        ("manual", "com.docker.compose.service=lab", "unknown"),
        ("manual", "com.docker.compose.project=nanfo-emulation", "unknown"),
        ("nanfo-training-" + CAMPAIGN, "", "unknown"),
        ("manual", "", "nanfo-emulation:campus-small-v1"),
    ],
)
def test_existing_labs_refused_without_stop(supervisor, monkeypatch, name, labels, image):
    monkeypatch.setattr(
        supervisor,
        "command",
        lambda argv, *a, **k: ""
        if any(item.startswith("ancestor=") for item in argv)
        else json.dumps({"Names": name, "Labels": labels, "Image": image}),
    )
    with pytest.raises(ValueError, match="owns the slot"):
        supervisor.exclusiveLab()


def test_budget_and_signal_cleanup_and_no_retry(supervisor, monkeypatch):
    cleaned = []

    def campaign():
        supervisor.requested = "signal_SIGTERM"
        supervisor.check()

    monkeypatch.setattr(supervisor, "campaign", campaign)
    monkeypatch.setattr(supervisor, "cleanup", lambda: cleaned.append(True))
    assert supervisor.run() == 0
    assert cleaned == [True] and supervisor.status["stop_reason"] == "signal_SIGTERM"
    supervisor.requested = None
    monkeypatch.setattr(s.time, "monotonic", lambda: supervisor.workDeadline)
    with pytest.raises(s.Stopped, match="budget_cleanup_reserve"):
        supervisor.check()


def test_execution_error_preserves_best(supervisor, monkeypatch):
    best = b'{"previous":"best"}'
    (supervisor.output / "best.json").write_bytes(best)
    calls = []

    def campaign():
        calls.append("campaign")
        raise RuntimeError("lost measured step")

    monkeypatch.setattr(supervisor, "campaign", campaign)
    monkeypatch.setattr(supervisor, "cleanup", lambda: calls.append("cleanup"))
    assert supervisor.run() == 1 and calls == ["campaign", "cleanup"]
    assert (supervisor.output / "best.json").read_bytes() == best


def test_owned_process_group_grace_then_kill_and_stale_pid(supervisor, monkeypatch):
    calls = []

    class Process:
        pid = 12345

        def poll(self):
            return None

        def wait(self, timeout):
            calls.append(("wait", timeout))
            if len(calls) == 2:
                raise subprocess.TimeoutExpired("fixture", timeout)

    monkeypatch.setattr(s.os, "killpg", lambda pid, sig: calls.append((pid, sig)))
    process = Process()
    supervisor.terminate(process, graceful=True)
    assert calls[0] == (12345, signal.SIGTERM)
    assert calls[2] == (12345, signal.SIGKILL)
    calls.clear()
    monkeypatch.setattr(process, "poll", lambda: 0)
    supervisor.terminate(process, graceful=True)
    assert calls == []


def test_locks_not_inherited_and_live_cleanup_refused(tmp_path):
    with s.lock(tmp_path / "lock"):
        with pytest.raises(ValueError, match="active"):
            with s.lock(tmp_path / "lock"):
                pytest.fail("double lock")
    target = tmp_path / "symlink"
    target.symlink_to(tmp_path / "lock")
    with pytest.raises(OSError):
        with s.lock(target):
            pytest.fail("symlink lock")


def test_paths_status_stop_never_signal_saved_pid(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(s, "ROOT", tmp_path)
    (tmp_path / "artifacts").mkdir()
    output = tmp_path / "artifacts" / "run"
    output.mkdir(mode=0o700)
    frozen = {**s.plan(IMAGE), "campaign_id": CAMPAIGN, "output": str(output)}
    (output / "plan.json").write_bytes(jsonBytes(frozen))
    (output / "status.json").write_bytes(jsonBytes({"pid": 1, "heartbeat_unix": 0}))
    monkeypatch.setattr(os, "kill", lambda *a: pytest.fail("stale PID signaled"))
    assert s.main(["status", "--output", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["heartbeat_stale"]
    assert s.main(["stop", "--output", str(output)]) == 0
    assert (output / "stop.request").exists()
    assert s.main(["stop", "--output", str(tmp_path)]) == 1
    link = tmp_path / "artifacts" / "link"
    link.symlink_to(output)
    with pytest.raises(ValueError, match="symlink"):
        s.outputPath(link)


def test_dry_run_no_docker_no_writes_or_resume(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "ROOT", tmp_path)
    (tmp_path / "artifacts").mkdir()
    output = tmp_path / "artifacts" / "new"
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("dry run launched"))
    args = [
        "run",
        "--operator-experiment",
        "--image-id",
        IMAGE,
        "--output",
        str(output),
        "--dry-run",
    ]
    assert s.main(args) == 0 and not output.exists()
    output.mkdir()
    assert s.main(args) == 1


@pytest.mark.parametrize("name", ["unrelated", "nanfo-training-../", "nanfo-training-" + "a" * 31])
def test_transport_restricts_names(name):
    with pytest.raises(ValueError):
        DockerTransport(name)
    DockerTransport("nanfo-training-" + CAMPAIGN)


@pytest.mark.parametrize("policy", ["constant0", "constant1"])
def test_constant_calibration_cli_and_report(tmp_path, monkeypatch, transport, policy):
    monkeypatch.setattr(cli, "DockerTransport", lambda *a: transport)
    output = tmp_path / policy
    assert (
        cli.main(
            [
                "evaluate",
                "--operator-experiment",
                "--policy",
                policy,
                "--split",
                "train",
                "--seed",
                "1001",
                "--episodes",
                "2",
                "--steps",
                "4",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    summary = json.loads((output / "summary.json").read_bytes())
    assert summary["evaluation_role"] == "calibration-not-held-out"
    assert summary["action_counts"][int(policy[-1])] == 8
    result = cli.report([output / "summary.json"])
    assert not result["comparable_held_out_schedules"]
    assert (output / "progress.json").exists()
    summary["episodes"][0]["reward"] += 1
    (output / "summary.json").write_bytes(jsonBytes(summary))
    with pytest.raises(ValueError, match="episode rewards"):
        cli.report([output / "summary.json"])


def test_disk_never_follows_unrelated_files(supervisor, tmp_path):
    target = tmp_path / "outside"
    target.write_text("keep")
    (supervisor.output / "linked").symlink_to(target)
    with pytest.raises(ValueError, match="non-regular"):
        supervisor.diskUsage()
    assert target.read_text() == "keep"


def test_session_commands_have_exact_splits_and_bounded_budget(supervisor, monkeypatch):
    commands = []
    monkeypatch.setattr(supervisor, "checkSources", lambda: None)
    monkeypatch.setattr(supervisor, "startLab", lambda stage: "nanfo-training-" + CAMPAIGN)
    monkeypatch.setattr(supervisor, "cleanup", lambda: None)

    def command(argv, *a, **k):
        commands.append(argv)
        raise RuntimeError("offline fixture stops before measurement")

    monkeypatch.setattr(supervisor, "command", command)
    for stage, split, seed, count in [
        ("train-01", "train", 1200, 12),
        ("validation-01", "validation", 2200, 6),
    ]:
        with pytest.raises(RuntimeError):
            supervisor.session(stage, split, seed, count)
    for argv in commands:
        assert argv[:3] == [s.sys.executable, "-m", "nanfo_routing"]
        assert argv[argv.index("--budget-seconds") + 1] == "600"
        assert "test" not in argv and "--operator-experiment" in argv
    assert "--split" not in commands[0]
    assert commands[1][commands[1].index("--split") + 1] == "validation"


def test_command_monitors_heartbeat_deadline_and_process_group(supervisor, monkeypatch):
    now = [supervisor.started]
    signals, beats = [], []

    class Pipe:
        def close(self):
            pass

    class Process:
        pid = 98765
        stdout, stderr = Pipe(), Pipe()
        ended = False

        def poll(self):
            return 0 if self.ended else None

        def wait(self, timeout):
            self.ended = True
            return 0

    process = Process()

    def popen(argv, **kwargs):
        assert kwargs["start_new_session"] and kwargs["close_fds"]
        assert kwargs["shell"] is False and kwargs["stdin"] == subprocess.DEVNULL
        return process

    class Selector:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def register(self, *args):
            pass

        def get_map(self):
            return {1: True}

        def select(self, timeout):
            now[0] += 1
            return []

    monkeypatch.setattr(s.subprocess, "Popen", popen)
    monkeypatch.setattr(s.selectors, "DefaultSelector", Selector)
    monkeypatch.setattr(s.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(s.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    monkeypatch.setattr(supervisor, "heartbeat", lambda: beats.append(now[0]))
    supervisor.workDeadline = now[0] + 5
    with pytest.raises(s.Stopped, match="budget_cleanup_reserve"):
        supervisor.command(["offline-command"], 600, session=True)
    assert len(beats) >= 3 and signals == [(process.pid, signal.SIGTERM)]
    assert now[0] < supervisor.hardDeadline and supervisor.process is None


def test_command_logs_rotate_and_stdout_is_bounded(supervisor, monkeypatch):
    class Pipe:
        def close(self):
            pass

    class Process:
        pid = 98765
        stdout, stderr = Pipe(), Pipe()

        def poll(self):
            return 0

        def wait(self, timeout):
            return 0

    class Selector:
        count = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def register(self, *args):
            pass

        def get_map(self):
            return {1: True} if self.count < 5 else {}

        def select(self, timeout):
            self.count += 1
            return [(SimpleNamespace(fd=1, data="stderr"), None)]

    monkeypatch.setattr(s, "LOG_LIMIT", 16)
    monkeypatch.setattr(s.subprocess, "Popen", lambda *a, **k: Process())
    monkeypatch.setattr(s.selectors, "DefaultSelector", Selector)
    monkeypatch.setattr(s.os, "read", lambda *a: b"fixture log\n")
    assert supervisor.command(["offline-command"], 10) == ""
    logs = list(supervisor.output.glob("command-*.stderr.log*"))
    assert len(logs) == 2 and sum(path.stat().st_size for path in logs) <= 32


def test_best_checkpoint_is_not_replaced_by_worse_validation(supervisor, monkeypatch):
    monkeypatch.setattr(supervisor, "exclusiveLab", lambda: None)
    monkeypatch.setattr(supervisor, "command", lambda *a, **k: IMAGE)
    monkeypatch.setattr(
        s,
        "report",
        lambda *a: {
            "matched_offered_schedules": True,
            "comparable_held_out_schedules": True,
        },
    )
    rewards = iter([0.5, 0.4, 0.3, 0.2])
    checked = {}
    calls = []

    def session(stage, split, first, count, policy="ppo", checkpoint=None):
        calls.append((stage, checkpoint))
        if stage.startswith("calibration-"):
            return calibration()[policy]
        if stage.startswith("baseline-"):
            return {"decision_mean": 0.1}
        if stage.startswith("train-"):
            index = int(stage[-2:])
            checked.clear()
            checked.update(
                {
                    "checkpoint_sha256": str(index),
                    "manifest": {
                        "weights_sha256": str(index),
                        "provenance": "measured-lab",
                        "transitions": index * 48,
                        "training_seeds": list(range(1200, 1200 + index * 12)),
                    },
                }
            )
            return {"checkpoint": dict(checked)}
        return {
            "checkpoint": dict(checked),
            "decision_mean": next(rewards),
            "evidence_sha256": "0" * 64,
        }

    monkeypatch.setattr(supervisor, "session", session)
    monkeypatch.setattr(s, "inspectCheckpoint", lambda *a: dict(checked))
    assert supervisor.campaign() == "validation_plateau"
    best = s.readJson(supervisor.output / "best.json")
    assert best["round"] == 1 and best["mean_decision_reward"] == 0.5
    assert supervisor.status["completed_rounds"] == 4
    resumes = [checkpoint for stage, checkpoint in calls if stage.startswith("train-")]
    assert resumes[0] is None
    assert resumes[-1] == supervisor.output / "train-03" / "checkpoint.ptz"


def test_signal_in_session_attempts_protocol_close(tmp_path, monkeypatch, transport):
    commands = []
    original = transport.exchange

    def exchange(request):
        commands.append(request.command)
        if request.command == "step":
            signal.raise_signal(signal.SIGTERM)
        return original(request)

    monkeypatch.setattr(transport, "exchange", exchange)
    monkeypatch.setattr(cli, "DockerTransport", lambda *a: transport)
    output = tmp_path / "interrupted"
    assert (
        cli.main(
            [
                "evaluate",
                "--operator-experiment",
                "--policy",
                "constant0",
                "--split",
                "train",
                "--seed",
                "1001",
                "--episodes",
                "2",
                "--steps",
                "4",
                "--output",
                str(output),
            ]
        )
        == 1
    )
    assert commands == ["reset", "step", "close"]
    summary = s.readJson(output / "summary.json")
    assert summary["status"] == "failed" and summary["cleanup_error"] is None
    assert not (output / "checkpoint.ptz").exists()


def test_docker_run_is_pinned_private_and_bounded(supervisor, monkeypatch):
    commands = []
    monkeypatch.setattr(supervisor, "exclusiveLab", lambda: None)

    def command(argv, *a, **k):
        commands.append(argv)
        if argv[1] == "run":
            (supervisor.output / "train-01.cid").write_text(CID)
            return CID
        return ""

    monkeypatch.setattr(supervisor, "command", command)
    assert supervisor.startLab("train-01") == "nanfo-training-" + CAMPAIGN
    argv = commands[0]
    for key, value in [
        ("--network", "none"),
        ("--cpus", "2"),
        ("--memory", "768m"),
        ("--pids-limit", "256"),
        ("--label", s.LABEL + "=" + CAMPAIGN),
    ]:
        assert argv[argv.index(key) + 1] == value
    assert "--pull=never" in argv and "--rm" in argv and IMAGE in argv
    assert argv.count("--mount") == 1 and argv.count("--tmpfs") == 2
    mount = argv[argv.index("--mount") + 1]
    assert mount == f"type=bind,src={supervisor.output / 'lab-output'},dst=/output"
    assert all(value not in argv for value in ["host", "--pid", "--volume", "nanfo-experiment"])
    assert commands[1][2] == CID
    compile(commands[1][-1], "readiness", "exec")


def test_malformed_summary_aborts_without_reward_or_retry(supervisor, monkeypatch):
    monkeypatch.setattr(supervisor, "checkSources", lambda: None)
    monkeypatch.setattr(supervisor, "startLab", lambda stage: "nanfo-training-" + CAMPAIGN)
    monkeypatch.setattr(supervisor, "cleanup", lambda: None)
    calls = []

    def command(argv, *a, **k):
        calls.append(argv)
        supervisor.sessionOutput.mkdir()
        (supervisor.sessionOutput / "summary.json").write_text('{"status":"completed"}')
        return ""

    monkeypatch.setattr(supervisor, "command", command)
    with pytest.raises(ValueError, match="incomplete or mismatched"):
        supervisor.session("train-01", "train", 1200, 12)
    assert len(calls) == 1 and supervisor.status["best_checkpoint"] is None


def test_source_drift_fails_before_docker(supervisor, monkeypatch):
    supervisor.frozen["client_source_sha256"] = {}
    monkeypatch.setattr(
        supervisor, "startLab", lambda *a: pytest.fail("source drift contacted Docker")
    )
    with pytest.raises(ValueError, match="sources changed"):
        supervisor.session("train-01", "train", 1200, 12)


def test_disk_cap_aborts_instead_of_deleting_evidence(supervisor):
    path = supervisor.output / "evidence.jsonl"
    with path.open("wb") as stream:
        stream.truncate(s.DISK_LIMIT)
    with pytest.raises(s.Stopped, match="disk_budget"):
        supervisor.diskUsage()
    assert path.stat().st_size == s.DISK_LIMIT
