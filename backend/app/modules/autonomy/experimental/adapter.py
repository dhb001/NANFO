"""Concrete ADR025 observer/transport ports over private authenticated receiver IPC.

Only operator composition supplies transport/credentials. No Docker dependency or
inference authority crosses into the application or frozen AI process.
"""

import asyncio
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.modules.autonomy.live_schemas import MeasuredFeatures, PassiveSnapshot
from app.modules.autonomy.schemas import Observation
from emulation.experimental_lab_contract import (
    IMAGE, MODEL, RESPONSE_LIMIT, SOURCE, VERSION, canonical, decode, protected_read,
)

from .schemas import (
    ExecutionReceipt, MeasuredFrame, PreparedAction, RecoveryReceipt, VerificationRecord, contract_digest,
)


class UnixTransport:
    def __init__(self, socket_path, timeout_seconds=50):
        self.socket_path, self.timeout = socket_path, timeout_seconds

    async def __call__(self, payload):
        async with asyncio.timeout(self.timeout):
            reader, writer = await asyncio.open_unix_connection(self.socket_path, limit=RESPONSE_LIMIT + 1)
            try:
                writer.write(payload)
                await writer.drain()
                writer.write_eof()
                chunks = bytearray()
                while len(chunks) <= RESPONSE_LIMIT:
                    part = await reader.read(min(65536, RESPONSE_LIMIT + 1 - len(chunks)))
                    if not part:
                        break
                    chunks.extend(part)
                return decode(chunks, RESPONSE_LIMIT)
            finally:
                writer.close()
                await writer.wait_closed()


class ExperimentalLabAdapter:
    """Implements ports.Observer and ports.Transport using one receiver.

    current_authority is an async owning-controller/Identity checkpoint. It MUST
    include durable STOP/lease checks; it is repeated during outstanding I/O.
    receiver_policy is the already hash-verified narrow operator configuration.
    """

    def __init__(self, *, policy, receiver_policy, receiver_policy_sha256, token_path,
                 transport, current_authority=None):
        self.policy = policy
        self.receiver_policy = receiver_policy
        self.policy_hash = receiver_policy_sha256
        self.token = protected_read(token_path).decode().strip()
        self.transport, self.current_authority = transport, current_authority
        self.fence = 0
        self.baseline = None
        self.last_execution = None
        self.synced = False
        self.keepalive = None
        self.heartbeat_lock = asyncio.Lock()
        p = receiver_policy
        if (p["controller_policy_sha256"] not in (None, contract_digest(policy))
                or p["image_id"] != IMAGE or p["source_sha256"] != SOURCE or p["model_sha256"] != MODEL
                or policy.runtime.image_sha256 != IMAGE.removeprefix("sha256:")
                or policy.runtime.source_sha256 != SOURCE or policy.checkpoint_sha256 != MODEL
                or policy.runtime.wrapper_sha256 != p["wrapper_sha256"]
                or policy.runtime.container_id != p["container_id"] or policy.max_actions != 1):
            raise ValueError("experimental_adapter_policy_binding_invalid")
        paths = {"route0": ("access1", "dist1", "access2"),
                 "route1": ("access1", "dist2", "access2")}
        if any(route.action_id not in paths or route.path != paths[route.action_id]
               or set(route.device_ids) != set(route.path)
               for route in policy.routes):
            raise ValueError("experimental_adapter_route_scope_invalid")

    def bind_checkpoint(self, checkpoint):
        """Called by Ports immediately after controller construction; no I/O."""
        if not callable(checkpoint):
            raise ValueError("experimental_checkpoint_required")
        self.current_authority = checkpoint

    async def _call(self, operation, *, action=None, duration=0, request_id=None, expiry=None):
        self.fence += 1
        request = dict(version=VERSION, request_id=str(request_id or uuid4()), fence=self.fence,
            policy_sha256=self.policy_hash, expires_at=expiry or time.time() + 60,
            operation=operation, action=action, duration_seconds=duration, token=self.token)
        response = await self.transport(canonical(request))
        if (set(response) != {"version", "request_id", "fence", "policy_sha256", "status", "evidence"}
                or any(response[k] != request[k] for k in ("version", "request_id", "fence", "policy_sha256"))
                or response["status"] not in ("ok", "rejected", "uncertain")
                or not isinstance(response["evidence"], dict)):
            raise ValueError("experimental_receiver_response_binding_invalid")
        if response["status"] != "ok":
            # Only the authenticated first STOP cause can identify receiver expiry.
            # Generic rejection (including a poor/incomplete window) stays failure.
            cause = response["evidence"].get("stop_cause") or {}
            if (operation == "heartbeat" and cause.get("reason") == "watchdog:action_expired"
                    and getattr(self, "action_expires_at", None) is not None
                    and time.time() >= self.action_expires_at):
                raise ValueError("experimental_action_expired")
            raise ValueError("experimental_receiver_uncertain_or_rejected")
        return response["evidence"]

    async def _heartbeat(self, checkpoint):
        # Serialize leases; a slower earlier docker-exec must not overwrite a
        # newer grant or race the background maintain task's sequence.
        lock = getattr(self, "heartbeat_lock", None)
        if lock is None:
            self.heartbeat_lock = lock = asyncio.Lock()
        async with lock:
            await self._renew_heartbeat(checkpoint)

    async def _renew_heartbeat(self, checkpoint):
        if checkpoint is None:
            raise ValueError("experimental_checkpoint_not_bound")
        if not self.synced:
            await self._sync()
        await checkpoint()
        await self._call("heartbeat", expiry=time.time() + self.receiver_policy["heartbeat_seconds"] - .25)

    async def _sync(self):
        result = await self._call("status")
        self.fence = max(self.fence, result["current_fence"])
        if hasattr(self, "policy"):
            binding = result.get("binding")
            if (not binding or binding["controller_policy_sha256"] != contract_digest(self.policy)
                    or binding["run_id"] != str(self.policy.measurement_run_id or self.policy.run_id)
                    or binding["receiver_policy_sha256"] != self.policy_hash):
                raise ValueError("experimental_receiver_not_bound_to_controller")
        self.synced = True

    async def _guarded(self, operation, checkpoint, **kwargs):
        await self._heartbeat(checkpoint)
        task = asyncio.create_task(self._call(operation, **kwargs))
        try:
            while not task.done():
                done, _ = await asyncio.wait({task}, timeout=.2)
                if done:
                    break
                await self._heartbeat(checkpoint)
            return await task
        except BaseException:
            # Authenticated STOP has independent ingress and interrupts original
            # mutation checks; uncertain execute is never resent.
            try:
                await asyncio.shield(self._call("stop"))
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            raise

    async def observe(self):
        evidence = await self._guarded("observe", self.current_authority)
        if self.keepalive is None:
            self.keepalive = asyncio.create_task(self._maintain_authority())
        self.baseline = evidence
        raw = evidence["frame"]
        data = raw["response"]["data"]
        ev = data["evidence"]
        if (not ev["measurement_complete"] or data["terminated"] or data["truncated"]
                or ev["provenance"] != {"lab_image_id": IMAGE, "source_sha256": SOURCE}
                or data["episode_id"] != str(self.policy.measurement_run_id or self.policy.run_id)):
            raise ValueError("experimental_frozen_frame_invalid")
        observed, started = self._times(evidence)
        now = datetime.now(UTC)
        age = (now - observed).total_seconds()
        if not 0 <= age <= self.policy.max_observation_age_seconds:
            raise ValueError("experimental_frame_stale_or_future")
        history = {"version": 3, "frames": [raw]}
        snapshot = PassiveSnapshot(version="nanfo.passive-measured-v4.v1",
            network_id=self.policy.network_id, workspace_id=self.policy.workspace_id,
            snapshot_id=uuid4(), run_id=data["episode_id"], observed_at=observed,
            window_started_at=started, published_at=now, source="operator-attested-measured-lab",
            contract_sha256=self.receiver_contract_hash, spec_sha256=ev["spec_hash"],
            history=history, history_sha256=contract_digest(history))
        observation = Observation(network_id=self.policy.network_id, workspace_id=self.policy.workspace_id,
            provider_id="experimental_owned_v4", contract=snapshot.version, observed_at=observed,
            collected_at=now, age_seconds=age, fresh=True, compatible=True,
            evidence=["measured_history:" + snapshot.history_sha256])
        return MeasuredFrame(snapshot=snapshot, features=MeasuredFeatures.model_validate(data["observation"]),
            observation=observation, runtime=self.policy.runtime, provenance=evidence)

    async def _maintain_authority(self):
        try:
            while True:
                await asyncio.sleep(.2)
                await self._heartbeat(self.current_authority)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Durable receiver STOP, and watchdog also restores if transport broke.
            try:
                await self._call("stop")
            except Exception:
                return

    async def close(self):
        if self.keepalive is not None:
            self.keepalive.cancel()
            await asyncio.gather(self.keepalive, return_exceptions=True)
            self.keepalive = None

    # Exact frozen contract, not a model loader override.
    receiver_contract_hash = "bbcbbadec55792fa3f01bef511c1e38b0e433e125f896cdc3e64f823325e0fe6"

    @staticmethod
    def _times(evidence):
        interval = evidence["frame"]["response"]["data"]["evidence"]["post_control_interval"]
        anchor = datetime.fromtimestamp(evidence["clock_wall"], UTC)
        return tuple(anchor + timedelta(seconds=interval[key] - evidence["clock_monotonic"])
                     for key in ("end", "start"))

    async def prepare(self, command):
        if (self.baseline is None or command.policy_sha256 != contract_digest(self.policy)
                or command.runtime != self.policy.runtime or command.route.action_id not in ("route0", "route1")):
            raise ValueError("experimental_prepare_binding_invalid")
        baseline = self.baseline["baseline"]
        if contract_digest(baseline) != self.baseline["binding"]["baseline_sha256"]:
            raise ValueError("experimental_original_baseline_mismatch")
        return PreparedAction(command=command, baseline=baseline, baseline_sha256=contract_digest(baseline),
            ownership_sha256=contract_digest({"runtime": self.policy.runtime.model_dump(mode="json"),
                                             "receiver_policy_sha256": self.policy_hash}))

    async def execute(self, action, checkpoint):
        command = action.command
        self.action_expires_at = command.expires_at.timestamp()
        evidence = await self._guarded("execute", checkpoint, action=int(command.route.action_id[-1]),
            request_id=command.request_id, expiry=command.expires_at.timestamp(),
            duration=min(self.receiver_policy["max_duration_seconds"],
                         (command.expires_at - datetime.now(UTC)).total_seconds()))
        self.last_execution = evidence
        return ExecutionReceipt(request_id=command.request_id, action_sha256=contract_digest(action),
            action_id=command.route.action_id, status="applied", evidence=evidence)

    async def verify(self, action):
        evidence = await self._guarded("verify", self.current_authority)
        data = evidence["frame"]["response"]["data"]
        obs, ev = data["observation"], data["evidence"]
        observed, started = self._times(evidence)
        wanted = int(action.command.route.action_id[-1])
        paths = evidence["readback"]["paths"]
        verified = (obs["previous_action"] == wanted and
                    all(paths[key]["action"] == wanted for key in ("h1->h3", "h3->h1")))
        return VerificationRecord(request_id=action.command.request_id, action_sha256=contract_digest(action),
            run_id=self.policy.run_id, action_id=action.command.route.action_id if verified else None,
            route_verified=verified, observed_at=observed, window_started_at=started,
            goodput_mbps=obs["goodput_mbps"], loss_fraction=obs["loss_fraction"], rtt_ms=obs["latency_ms"],
            probe_sent=ev["ping"]["sent"], probe_received=ev["ping"]["received"],
            traffic_bytes=ev["udp_received"][0]["bytes"], provenance=evidence)

    async def recover(self, action, checkpoint):
        await self.close()
        await checkpoint()  # recovery ownership, not renewed inference/actor permission
        if not self.synced:
            await self._sync()
        evidence = await self._call("recover")
        restoration = evidence.get("restoration", {})
        readback = restoration.get("readback", {})
        exact = (restoration.get("baseline_sha256") == action.baseline_sha256
                 and restoration.get("baseline") == action.baseline
                 and restoration.get("owned_empty") is True
                 and restoration.get("original_forwarding_verified") is True
                 and readback.get("tables") == action.baseline["tables"]
                 and all(readback.get("paths", {}).get(k, {}).get("nodes") == v["nodes"]
                         for k, v in action.baseline["paths"].items()))
        return RecoveryReceipt(request_id=action.command.request_id, action_sha256=contract_digest(action),
            baseline_sha256=action.baseline_sha256, status="restored" if exact else "uncertain", evidence=evidence)

    async def stop(self):
        await self.close()
        return await self._call("stop")
