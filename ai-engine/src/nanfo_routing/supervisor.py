"""Explicit operator-only, non-resumable two-hour measured training supervisor."""

import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

from .artifacts import atomicWrite, inspectCheckpoint, runtimeVersions
from .cli import report
from .contracts import CONTRACT_HASH, SCENARIOS, SPLITS, jsonBytes, parseJson
from .ppo import PPOConfig

ROOT = Path(__file__).resolve().parents[2]
LABEL = "org.nanfo.training.campaign"
GLOBAL_LOCK = Path("/tmp/nanfo-training-supervisor.lock")
IMAGE_PATTERN = r"sha256:[0-9a-f]{64}"
ID_PATTERN = r"[0-9a-f]{64}"
LOG_LIMIT = 1024 * 1024
DISK_LIMIT = 1024 * 1024 * 1024


@dataclass(frozen=True)
class Config:
    budget_seconds: int = 7200
    cleanup_reserve_seconds: int = 120
    session_budget_seconds: int = 600
    max_rounds: int = 8
    min_rounds: int = 3
    min_transitions: int = 144
    patience: int = 3
    min_delta: float = 0.02
    train_episodes: int = 12
    validation_episodes: int = 6
    steps: int = 4
    window: int = 5
    model_seed: int = 42
    rollout: int = 16
    disk_limit_bytes: int = DISK_LIMIT
    round_admission_seconds: int = 1500


CONFIG = Config()


def readJson(path, limit=8 * LOG_LIMIT):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
            raise ValueError("unsafe or oversized supervisor artifact")
        value = parseJson(source.read(limit + 1))
        if type(value) is not dict:
            raise ValueError("supervisor artifact must be a JSON object")
        return value


def outputPath(path, *, existing=True):
    path = Path(os.path.abspath(path))
    base = ROOT / "artifacts"
    if path.parent != base or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", path.name):
        raise ValueError("output must be ai-engine/artifacts/<simple-run-name>")
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError("symlink output paths are forbidden")
    if not base.is_dir() or (existing and not path.is_dir()):
        raise ValueError("output parent/run directory does not exist")
    if existing:
        info = path.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("run directory must be private and owned by the current user")
    return path


@contextmanager
def lock(path):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
        ):
            raise ValueError("unsafe supervisor lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError(
                "supervisor is active; request stop, do not clean a live owner"
            ) from exc
        yield
    finally:
        os.close(fd)


def seeds(split, first, count):
    return [
        {"seed": seed, "scenario": SCENARIOS[(seed - SPLITS[split][0]) % len(SCENARIOS)]}
        for seed in range(first, first + count)
    ]


def plan(image):
    if not re.fullmatch(IMAGE_PATTERN, image):
        raise ValueError("image must be an already-local immutable sha256 image ID")
    return {
        "version": 1,
        "config": asdict(CONFIG),
        "ppo_config": PPOConfig(seed=CONFIG.model_seed, rollout=CONFIG.rollout).model_dump(),
        "image_id": image,
        "contract_hash": CONTRACT_HASH,
        "calibration": seeds("train", 1001, 2),
        "calibration_policies": ["constant0", "constant1"],
        "validation": seeds("validation", 2200, CONFIG.validation_episodes),
        "baseline_policies": ["constant0", "constant1", "heuristic"],
        "training": [
            seeds("train", 1200 + index * CONFIG.train_episodes, CONFIG.train_episodes)
            for index in range(CONFIG.max_rounds)
        ],
        "test": "not accessed",
        "automatic_campaign_resume": False,
        "resume_within_campaign": "only previous successfully validated block",
        "selection_metric": "arithmetic mean measured decision reward; validation only",
        "learnability_gate": "path0: constant1 - constant0 > .02; path1: reverse > .02",
        "quality_gate": "after >=3 rounds/144 transitions best PPO must beat best constant by .02",
        "plateau": "3 rounds without >.02 improvement; minimum 3 rounds/144 transitions",
        "limitations": [
            "Fixed validation is model selection, not a final test or confidence interval.",
            "Early stop is not convergence, superiority, safety or beneficial adaptation.",
            "At most eight rounds; startup, audits and cleanup consume the same 7200 seconds.",
            "Privileged disposable Mininet container; no host network/PID/credential mounts.",
        ],
    }


def loadPlan(output):
    value = readJson(output / "plan.json")
    if not re.fullmatch(r"[0-9a-f]{32}", value.get("campaign_id", "")):
        raise ValueError("invalid campaign identity")
    if value.get("output") != str(output):
        raise ValueError("campaign output identity differs")
    expected = plan(value["image_id"])
    if any(value.get(key) != item for key, item in expected.items()):
        raise ValueError("campaign plan differs from frozen configuration")
    return value


def earlyStop(rewards, transitions, baseline):
    if not rewards or any(not math.isfinite(value) for value in [*rewards, baseline]):
        raise ValueError("missing/nonfinite selection reward")
    significantBest, stale = rewards[0], 0
    for value in rewards[1:]:
        if value > significantBest + CONFIG.min_delta:
            significantBest, stale = value, 0
        else:
            stale += 1
    if len(rewards) < CONFIG.min_rounds or transitions < CONFIG.min_transitions:
        return None
    if max(rewards) <= baseline + CONFIG.min_delta:
        return "low_quality_no_advantage_over_constant"
    return "validation_plateau" if stale >= CONFIG.patience else None


def learnability(summaries):
    margins = {}
    for index, scenario in enumerate(("path0", "path1")):
        totals = []
        for policy in ("constant0", "constant1"):
            episode = summaries[policy]["episodes"][index]
            if episode["scenario"] != scenario or episode["seed"] != 1001 + index:
                raise ValueError("calibration scenario/seed mismatch")
            totals.append(episode["reward"] / CONFIG.steps)
        margins[scenario] = (totals[1] - totals[0]) * (1 if index == 0 else -1)
    if any(not math.isfinite(value) or value <= CONFIG.min_delta for value in margins.values()):
        raise ValueError(
            f"learnability preflight failed: stationary alternate-route reward margins {margins}; "
            "inspect measured phases/routes/rewards; no training or synthetic fallback"
        )
    return margins


class Stopped(RuntimeError):
    pass


class Supervisor:
    def __init__(self, output, frozen, started=None):
        self.output, self.frozen = output, frozen
        self.started = time.monotonic() if started is None else started
        self.hardDeadline = self.started + CONFIG.budget_seconds
        self.workDeadline = self.hardDeadline - CONFIG.cleanup_reserve_seconds
        self.requested = None
        self.process = None
        self.commandIndex = 0
        self.sessionOutput = None
        self.status = {
            "version": 1,
            "campaign_id": frozen["campaign_id"],
            "state": "running",
            "stage": "preflight",
            "pid": os.getpid(),
            "child_pid": None,
            "container_id": None,
            "hard_deadline_unix": time.time() + self.hardDeadline - time.monotonic(),
            "work_deadline_unix": time.time() + self.workDeadline - time.monotonic(),
            "completed_rounds": 0,
            "train_transitions": 0,
            "last_reward": None,
            "baseline": {},
            "best_checkpoint": None,
            "stop_reason": None,
            "cleanup_error": None,
        }

    def heartbeat(self):
        self.status.update(
            heartbeat_unix=time.time(),
            elapsed_seconds=time.monotonic() - self.started,
            child_pid=self.process.pid if self.process else None,
        )
        if (
            self.sessionOutput
            and self.status["stage"] not in ("cleanup", "poststop_cleanup", "finished")
            and (self.sessionOutput / "progress.json").exists()
        ):
            self.status["child_progress"] = readJson(
                self.sessionOutput / "progress.json", LOG_LIMIT
            )
        atomicWrite(self.output / "status.json", jsonBytes(self.status))

    def check(self):
        if self.requested or (self.output / "stop.request").exists():
            raise Stopped(self.requested or "operator_stop")
        if time.monotonic() >= self.workDeadline:
            raise Stopped("budget_cleanup_reserve")

    def checkSources(self):
        actual = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(Path(__file__).parent.glob("*.py"))
        }
        if actual != self.frozen["client_source_sha256"]:
            raise ValueError("client sources changed during frozen campaign; stop without resume")
        if runtimeVersions() != self.frozen["runtime_versions"]:
            raise ValueError("runtime changed during frozen campaign")

    def diskUsage(self):
        size, count = 0, 0

        def unreadable(error):
            raise error

        for directory, dirs, files in os.walk(self.output, followlinks=False, onerror=unreadable):
            for name in [*dirs, *files]:
                try:
                    info = (Path(directory) / name).lstat()
                except FileNotFoundError:
                    # Producer atomic writes can rename a temporary file during this scan.
                    continue
                if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                    raise ValueError("non-regular artifact in private run directory")
                if stat.S_ISREG(info.st_mode):
                    if info.st_nlink != 1:
                        raise ValueError("hard-linked campaign artifact")
                    size += info.st_size
                count += 1
                if count > 50000:
                    raise ValueError("campaign file-count limit")
        self.status["disk_bytes"] = size
        # Leave headroom for final evidence, summaries, and cleanup diagnostics.
        if size >= CONFIG.disk_limit_bytes - 64 * LOG_LIMIT:
            raise Stopped("disk_budget")

    def terminate(self, process, *, graceful):
        # Only signal a process group created and still held by this Popen instance.
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(
                timeout=min(
                    50 if graceful else 2, max(0.1, self.hardDeadline - time.monotonic() - 50)
                )
            )
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)
        except ProcessLookupError:
            process.wait(timeout=3)

    def command(self, argv, timeout, *, cleanup=False, session=False):
        if not cleanup:
            self.check()
            self.diskUsage()
        deadline = min(
            time.monotonic() + timeout,
            self.hardDeadline if cleanup else self.workDeadline,
        )
        if deadline <= time.monotonic():
            raise Stopped("hard_deadline" if cleanup else "budget_cleanup_reserve")
        self.commandIndex += 1
        prefix = self.output / f"command-{self.commandIndex:03}"
        captured = bytearray()
        sizes = {"stdout": 0, "stderr": 0}
        streams = {}
        process = None
        try:
            for name in sizes:
                streams[name] = Path(f"{prefix}.{name}.log").open("xb")
            process = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                close_fds=True,
                shell=False,
                cwd=ROOT,
                env={
                    **os.environ,
                    "PYTHONUNBUFFERED": "1",
                    "OMP_NUM_THREADS": "2",
                    "MKL_NUM_THREADS": "2",
                },
            )
            self.process = process
            self.status["command"] = argv
            self.heartbeat()
            nextHeartbeat = time.monotonic() + 2
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ, "stdout")
                selector.register(process.stderr, selectors.EVENT_READ, "stderr")
                while selector.get_map() or process.poll() is None:
                    if not cleanup:
                        self.check()
                    if time.monotonic() >= deadline:
                        raise Stopped("command_timeout")
                    for key, _ in selector.select(0.2):
                        chunk = os.read(key.fd, 8192)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        name = key.data
                        if sizes[name] + len(chunk) > LOG_LIMIT:
                            streams[name].close()
                            Path(f"{prefix}.{name}.log").replace(Path(f"{prefix}.{name}.log.1"))
                            streams[name] = Path(f"{prefix}.{name}.log").open("xb")
                            sizes[name] = 0
                        streams[name].write(chunk)
                        streams[name].flush()
                        sizes[name] += len(chunk)
                        if name == "stdout":
                            captured.extend(chunk)
                            if len(captured) > LOG_LIMIT:
                                raise ValueError("command response exceeds bound")
                    if time.monotonic() >= nextHeartbeat:
                        if not cleanup:
                            self.diskUsage()
                        self.heartbeat()
                        nextHeartbeat = time.monotonic() + 2
            if process.wait(timeout=1) != 0:
                raise RuntimeError(f"command failed; inspect {prefix.name} logs (no retry)")
            return captured.decode("utf-8")
        finally:
            if process:
                self.terminate(process, graceful=session)
                process.stdout.close()
                process.stderr.close()
            self.process = None
            for stream in streams.values():
                stream.close()

    def exclusiveLab(self):
        journal = ROOT.parent / "emulation" / "results" / ".journal.json"
        if journal.exists() or journal.is_symlink():
            raise ValueError("manual journal exists; reconcile manually, never delete it")
        sameImage = self.command(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                "ancestor=" + self.frozen["image_id"],
                "--format",
                "{{.ID}}",
            ],
            10,
        ).strip()
        if sameImage:
            raise ValueError("existing container uses pinned lab image; nothing was stopped")
        raw = self.command(["docker", "ps", "-a", "--no-trunc", "--format", "{{json .}}"], 10)
        for line in raw.splitlines():
            row = parseJson(line)
            if (
                row["Names"] == "nanfo-experiment"
                or row["Names"].startswith(("nanfo-training-", "nanfo-emulation-"))
                or "com.docker.compose.project=nanfo-emulation" in row.get("Labels", "")
                or "com.docker.compose.service=lab" in row.get("Labels", "")
                or row["Image"] in (self.frozen["image_id"], self.frozen["image_id"][7:19])
                or row["Image"].startswith("nanfo-emulation:")
                or LABEL in row.get("Labels", "")
            ):
                raise ValueError("existing lab/experiment owns the slot; nothing was stopped")

    def startLab(self, stage, mode="sdn"):
        self.exclusiveLab()
        self.check()
        name = "nanfo-training-" + self.frozen["campaign_id"]
        cidfile = f"{stage}.cid"
        owner = {
            "campaign_id": self.frozen["campaign_id"],
            "name": name,
            "image_id": self.frozen["image_id"],
            "cidfile": cidfile,
        }
        atomicWrite(self.output / "owner.json", jsonBytes(owner))
        # Docker's cidfile survives a lost run response; never discover ownership by name.
        raw = self.command(
            [
                "docker",
                "run",
                "--detach",
                "--rm",
                "--pull=never",
                "--name",
                name,
                "--cidfile",
                str(self.output / cidfile),
                "--label",
                f"{LABEL}={owner['campaign_id']}",
                "--network",
                "none",
                "--privileged",
                "--cpus",
                "2",
                "--memory",
                "768m",
                "--memory-swap",
                "768m",
                "--pids-limit",
                "256",
                "--tmpfs",
                "/run:exec,size=64m",
                "--tmpfs",
                "/tmp:exec,size=64m",
                "--mount",
                f"type=bind,src={self.output / 'lab-output'},dst=/output",
                "--log-driver",
                "json-file",
                "--log-opt",
                "max-size=2m",
                "--log-opt",
                "max-file=2",
                "--env",
                "EMULATION_CONTROL_ENABLED=false",
                "--env",
                "NANFO_LAB_IMAGE_ID=" + owner["image_id"],
                owner["image_id"],
                "--experiment",
                "--mode",
                mode,
                "--output",
                "/output",
            ],
            30,
        ).strip()
        captured = self.containerId(owner)
        if raw != captured:
            raise ValueError("Docker run response differs from captured container ID")
        self.status["container_id"] = captured
        self.command(
            [
                "docker",
                "exec",
                captured,
                "python",
                "-c",
                "from pathlib import Path; import time,sys; end=time.monotonic()+75; "
                'exec("while time.monotonic()<end and not '
                "Path('/run/nanfo/experiment.sock').is_socket(): time.sleep(.25)\"); "
                "sys.exit(not Path('/run/nanfo/experiment.sock').is_socket())",
            ],
            80,
        )
        return name

    def containerId(self, owner):
        if (
            owner.get("campaign_id") != self.frozen["campaign_id"]
            or owner.get("name") != "nanfo-training-" + self.frozen["campaign_id"]
            or owner.get("image_id") != self.frozen["image_id"]
            or not re.fullmatch(r"[a-z0-9-]+\.cid", owner.get("cidfile", ""))
        ):
            raise ValueError("invalid cleanup ownership record")
        path = self.output / owner["cidfile"]
        if not path.exists() and not path.is_symlink():
            return None
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "r") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 65:
                raise ValueError("unsafe captured container ID file")
            value = source.read(66).strip()
        if not re.fullmatch(ID_PATTERN, value):
            raise ValueError("invalid captured container ID")
        return value

    def cleanup(self):
        if not (self.output / "owner.json").exists():
            return
        owner = readJson(self.output / "owner.json")
        identity = self.containerId(owner)
        if identity is None:
            # A create interrupted before cidfile publication is uncertain, not ownership proof.
            raise ValueError("no captured container ID; cannot authorize cleanup by name")
        lookup = [
            "docker",
            "ps",
            "-a",
            "--no-trunc",
            "--filter",
            f"id={identity}",
            "--format",
            "{{.ID}}",
        ]

        def waitAbsent():
            deadline = min(time.monotonic() + 30, self.hardDeadline)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError(
                        "owned container removal not verified within cleanup deadline"
                    )
                raw = self.command(lookup, min(10, remaining), cleanup=True).strip()
                if raw and raw != identity:
                    raise ValueError("Docker ID lookup mismatch")
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "owned container removal not verified within cleanup deadline"
                    )
                if not raw:
                    self.status["container_id"] = None
                    return
                self.heartbeat()
                time.sleep(min(1, max(0, deadline - time.monotonic())))

        raw = self.command(lookup, 10, cleanup=True).strip()
        if not raw:
            self.status["container_id"] = None
            return
        if raw != identity:
            raise ValueError("Docker ID lookup mismatch")
        for argv, timeout in (
            (["docker", "inspect", "--format", "{{json .}}", identity], 10),
            (["docker", "stop", "--time", "20", identity], 30),
        ):
            try:
                response = self.command(argv, timeout, cleanup=True)
            except Stopped:
                raise
            except (RuntimeError, OSError, subprocess.SubprocessError):
                # --rm may remove this exact owner between lookup, inspect and stop.
                # Only a successful absence query resolves that race, never an error/name.
                waitAbsent()
                return
            if argv[1] == "inspect":
                details = parseJson(response)
                if (
                    details["Id"] != identity
                    or details["Name"] != "/" + owner["name"]
                    or type(details["Config"]["Labels"]) is not dict
                    or details["Config"]["Labels"].get(LABEL) != owner["campaign_id"]
                    or details["Image"] != owner["image_id"]
                ):
                    raise ValueError("container ownership mismatch; refusing to stop anything")
        waitAbsent()

    def session(self, stage, split, first, count, policy="ppo", checkpoint=None):
        self.checkSources()
        self.status["stage"] = stage
        self.sessionOutput = self.output / stage
        self.status["child_progress"] = None
        self.heartbeat()
        name = self.startLab(stage)
        training = stage.startswith("train-")
        argv = [
            sys.executable,
            "-m",
            "nanfo_routing",
            "train" if training else "evaluate",
            "--operator-experiment",
            "--container",
            name,
            "--budget-seconds",
            "600",
            "--seed",
            str(first),
            "--episodes",
            str(count),
            "--steps",
            "4",
            "--window",
            "5",
            "--model-seed",
            "42",
            "--rollout",
            "16",
            "--output",
            str(self.sessionOutput),
        ]
        if not training:
            argv += ["--split", split, "--policy", policy]
        if checkpoint:
            argv += ["--resume" if training else "--checkpoint", str(checkpoint)]
        self.command(argv, 600, session=True)
        self.cleanup()
        self.check()
        summary = readJson(self.sessionOutput / "summary.json")
        expected = {
            "status": "completed",
            "failure": None,
            "cleanup_error": None,
            "kind": "train" if training else "evaluation",
            "split": split,
            "policy": policy,
            "mode": "sdn",
            "seeds": list(range(first, first + count)),
            "window_seconds": 5,
            "episode_steps": 4,
            "invalid_windows": 0,
            "valid_transitions": count * CONFIG.steps,
        }
        if any(summary.get(key) != value for key, value in expected.items()):
            raise ValueError("incomplete or mismatched session summary; no retry")
        if summary["lab_provenance"]["lab_image_id"] != self.frozen["image_id"]:
            raise ValueError("measured image differs from frozen image")
        if self.status.get("spec_hash", summary["spec_hash"]) != summary["spec_hash"]:
            raise ValueError("lab spec drift across sessions")
        self.status["spec_hash"] = summary["spec_hash"]
        audited = report([self.sessionOutput / "summary.json"])["sessions"][0]
        if stage.startswith("calibration-"):
            for row in audited["reconstructed_phases"]:
                if row["phase"]["background_path"] != int(row["scenario"] == "path1"):
                    raise ValueError("calibration is not stationary path0/path1 in raw evidence")
        mean = audited["derived_metrics"]["mean_reward"]
        if type(mean) not in (int, float) or not math.isfinite(mean):
            raise ValueError("invalid measured decision mean")
        # Calibration uses episode means, so verify those against their raw reward records too.
        for episode in summary["episodes"]:
            if (
                episode["windows"] != CONFIG.steps
                or len(episode["rewards"]) != CONFIG.steps
                or not math.isclose(
                    episode["reward"], sum(row["total"] for row in episode["rewards"])
                )
            ):
                raise ValueError("invalid episode reward summary")
        summary["decision_mean"] = mean
        atomicWrite(self.sessionOutput / "audit.json", jsonBytes(audited))
        self.diskUsage()
        return summary

    def campaign(self):
        self.exclusiveLab()
        image = self.command(
            [
                "docker",
                "image",
                "inspect",
                self.frozen["image_id"],
                "--format",
                "{{.Id}}",
            ],
            10,
        ).strip()
        if image != self.frozen["image_id"]:
            raise ValueError("local image pin mismatch; builds/pulls are forbidden")
        calibration = {
            policy: self.session("calibration-" + policy, "train", 1001, 2, policy)
            for policy in self.frozen["calibration_policies"]
        }
        matched = report(
            [
                self.output / ("calibration-" + policy) / "summary.json"
                for policy in self.frozen["calibration_policies"]
            ]
        )
        if not matched["matched_offered_schedules"]:
            raise ValueError("calibration policies did not measure matching schedules")
        self.status["learnability_margins"] = learnability(calibration)
        for policy in self.frozen["baseline_policies"]:
            result = self.session("baseline-" + policy, "validation", 2200, 6, policy)
            self.status["baseline"][policy] = result["decision_mean"]
            self.heartbeat()
        baselinePaths = [
            self.output / ("baseline-" + policy) / "summary.json"
            for policy in self.frozen["baseline_policies"]
        ]
        if not report(baselinePaths)["comparable_held_out_schedules"]:
            raise ValueError("baseline schedules/spec/dataplane differ")
        baseline = max(self.status["baseline"][key] for key in ("constant0", "constant1"))
        rewards, previous = [], None
        for index in range(CONFIG.max_rounds):
            self.check()
            if self.workDeadline - time.monotonic() < CONFIG.round_admission_seconds:
                return "insufficient_budget_for_round"
            train = self.session(
                f"train-{index + 1:02}", "train", 1200 + index * 12, 12, checkpoint=previous
            )
            checkpoint = self.output / f"train-{index + 1:02}" / "checkpoint.ptz"
            checked = inspectCheckpoint(checkpoint)
            manifest = checked["manifest"]
            if (
                checked != train["checkpoint"]
                or manifest["provenance"] != "measured-lab"
                or manifest["transitions"] != (index + 1) * 48
                or manifest["training_seeds"] != list(range(1200, 1200 + (index + 1) * 12))
            ):
                raise ValueError("checkpoint counters/provenance differ from successful blocks")
            validation = self.session(
                f"validation-{index + 1:02}", "validation", 2200, 6, checkpoint=checkpoint
            )
            if validation["checkpoint"] != checked:
                raise ValueError("validation checkpoint differs from completed training block")
            if not report(
                [
                    *baselinePaths,
                    self.output / f"validation-{index + 1:02}" / "summary.json",
                ]
            )["comparable_held_out_schedules"]:
                raise ValueError("PPO validation differs from frozen baseline schedules")
            self.check()
            reward = validation["decision_mean"]
            if not rewards or reward > max(rewards):
                best = {
                    "checkpoint": str(checkpoint.relative_to(self.output)),
                    "checkpoint_sha256": checked["checkpoint_sha256"],
                    "weights_sha256": manifest["weights_sha256"],
                    "validation_evidence_sha256": validation["evidence_sha256"],
                    "round": index + 1,
                    "mean_decision_reward": reward,
                }
                atomicWrite(self.output / "best.json", jsonBytes(best))
                self.status["best_checkpoint"] = best
            previous = checkpoint
            rewards.append(reward)
            self.status.update(
                completed_rounds=index + 1,
                train_transitions=(index + 1) * 48,
                last_reward=reward,
                validation_rewards=rewards,
            )
            self.heartbeat()
            reason = earlyStop(rewards, (index + 1) * 48, baseline)
            if reason:
                return reason
        return "max_rounds"

    def run(self):
        handlers = {}

        def stop(signum, frame):
            self.requested = "signal_" + signal.Signals(signum).name

        for item in (signal.SIGTERM, signal.SIGINT):
            handlers[item] = signal.signal(item, stop)
        code = 0
        try:
            self.heartbeat()
            self.status["stop_reason"] = self.campaign()
            self.status["state"] = "stopped"
        except Stopped as exc:
            self.status.update(state="stopped", stop_reason=str(exc))
            if str(exc) in ("command_timeout", "hard_deadline"):
                self.status["state"], code = "failed", 1
        except (
            ValueError,
            RuntimeError,
            OSError,
            TypeError,
            KeyError,
            subprocess.SubprocessError,
        ) as exc:
            self.status.update(state="failed", stop_reason="execution_error", error=str(exc)[:2048])
            code = 1
        finally:
            self.status["stage"] = "cleanup"
            try:
                self.cleanup()
            except (
                ValueError,
                RuntimeError,
                OSError,
                KeyError,
                TypeError,
                subprocess.SubprocessError,
            ) as exc:
                self.status.update(state="failed", cleanup_error=str(exc)[:2048])
                code = 1
            self.status["stage"] = "finished"
            try:
                self.heartbeat()
            finally:
                for item, handler in handlers.items():
                    signal.signal(item, handler)
        return code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="new campaign only; never extends/resumes a deadline")
    run.add_argument("--operator-experiment", required=True, action="store_true")
    run.add_argument("--image-id", required=True)
    run.add_argument(
        "--dry-run", action="store_true", help="print frozen plan; no Docker or writes"
    )
    run.add_argument("--output", type=Path, required=True)
    for name in ("status", "stop", "cleanup"):
        sub = commands.add_parser(name)
        sub.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    started = time.monotonic()
    try:
        output = outputPath(args.output, existing=args.command != "run")
        if args.command == "run":
            frozen = plan(args.image_id)
            if output.exists():
                raise ValueError("existing output refused; automatic resume is disabled")
            if args.dry_run:
                print(json.dumps({**frozen, "output": str(output)}, indent=2))
                return 0
            with lock(GLOBAL_LOCK):
                output.mkdir(mode=0o700)
                (output / "lab-output").mkdir(mode=0o700)
                frozen.update(campaign_id=uuid.uuid4().hex, output=str(output))
                frozen["runtime_versions"] = runtimeVersions()
                frozen["client_source_sha256"] = {
                    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in sorted(Path(__file__).parent.glob("*.py"))
                }
                atomicWrite(output / "plan.json", jsonBytes(frozen))
                with lock(output / "run.lock"):
                    return Supervisor(output, frozen, started).run()
        frozen = loadPlan(output)
        if args.command == "status":
            result = readJson(output / "status.json")
            # Do not probe or signal a saved PID: it may have been reused after a crash.
            result["heartbeat_stale"] = time.time() - result["heartbeat_unix"] > 10
            result["stop_requested"] = (output / "stop.request").exists()
            print(json.dumps(result, indent=2))
        elif args.command == "stop":
            atomicWrite(output / "stop.request", jsonBytes({"campaign_id": frozen["campaign_id"]}))
            print(json.dumps({"status": "stop_requested", "signals_sent": False}))
        else:
            with lock(output / "run.lock"):
                supervisor = Supervisor(output, frozen)
                supervisor.commandIndex = max(
                    [
                        900,
                        *[
                            int(path.name.split(".")[0].split("-")[1])
                            for path in output.glob("command-*.stdout.log")
                            if re.fullmatch(r"command-[0-9]+\.stdout\.log", path.name)
                        ],
                    ]
                )
                supervisor.hardDeadline = time.monotonic() + 110
                if (output / "status.json").exists():
                    supervisor.status = readJson(output / "status.json")
                    supervisor.started -= supervisor.status.get("elapsed_seconds", 0)
                supervisor.status.update(stage="poststop_cleanup", child_pid=None)
                try:
                    supervisor.cleanup()
                except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
                    supervisor.status.update(state="failed", cleanup_error=str(exc)[:2048])
                    supervisor.heartbeat()
                    raise
                else:
                    supervisor.status.update(stage="finished", cleanup_error=None)
                    if supervisor.status["state"] == "running":
                        supervisor.status.update(state="stopped", stop_reason="poststop_cleanup")
                    supervisor.heartbeat()
            print(json.dumps({"status": "owned_cleanup_verified"}))
        return 0
    except (
        ValueError,
        RuntimeError,
        OSError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)[:2048]}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
