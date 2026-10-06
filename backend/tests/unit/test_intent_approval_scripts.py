"""ADR-028 request sequencing of the live verifiers and demo tooling (mocked HTTP only).

A small contract model of the API (``FakeIntentApi``) enforces the new execution rules
— distinct approver, stored idempotency key, echoed approval binding, bound passing
simulation for high-impact actions — so these tests fail if a script regresses to the
pre-ADR-028 sequence. Nothing here claims live execution.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import httpx
import pytest

from app.core.config import get_settings
from app.modules.simulation.evaluator import advance, initial_checkpoint, output
from app.modules.simulation.modeled import limits_respect_policy, policy_floors
from app.modules.simulation.schemas import ScenarioConfig
from scripts import prepare_strathmore_demo as strathmore
from scripts.verify_execution import (
    POLICY_LIMITS,
    ApprovalFlow,
    VerificationError,
    execute_body,
    intent_payload,
    policy_limits,
    policy_scenario_config,
    requires_simulation,
    run_bound_simulation,
)

REQUESTER, APPROVER = "Bearer requester-token", "Bearer approver-token"
WORKSPACE, NETWORK = str(uuid.UUID(int=1)), str(uuid.UUID(int=2))
HIGH_IMPACT = {"reroute_path", "isolate_vlan"}


def _envelope(data=None, *, errors=None, status=200, mode="emulation"):
    return httpx.Response(status, json={"success": errors is None, "data": data, "errors": errors,
                                        "meta": {"request_id": "r", "execution_mode": mode}})


class FakeIntentApi:
    """Server-side ADR-028 rules for validate/simulate/execute, recording every request."""

    def __init__(self, *, lab=True, simulation_passes=True, polls_before_completion=1, store_key=True):
        self.lab, self.simulation_passes, self.store_key = lab, simulation_passes, store_key
        self.polls_before_completion = polls_before_completion
        self.calls: list[tuple[str, str, str | None, dict | None]] = []
        self.intents: dict[str, dict] = {}
        self.simulations: dict[str, dict] = {}
        self.executions: dict[str, dict] = {}
        self.members: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        token = request.headers.get("Authorization")
        self.calls.append((request.method, request.url.path, token, body))
        path = request.url.path
        if path == "/api/v1/intents/validate":
            return self._validate(request, body, token)
        if path == "/api/v1/simulations/start":
            return self._start(body)
        if path.startswith("/api/v1/simulations/"):
            return self._simulation(path.rsplit("/", 1)[1])
        if path == "/api/v1/intents/execute":
            return self._execute(body, token)
        if path == "/api/v1/auth/login":
            who = "approver" if body["email"].startswith("approver") else "requester"
            return _envelope({"access_token": f"{who}-token"})
        if path == "/api/v1/auth/me":
            return _envelope({"user_id": "approver-user" if token == APPROVER else "requester-user"})
        if path.endswith("/members"):
            self.members.append({"token": token, **body})
            return _envelope({"org_id": "org", **body}, status=201)
        if path.startswith("/api/v1/intents/"):
            return _envelope(self.intents[path.rsplit("/", 1)[1]])
        return httpx.Response(404, json={"success": False, "data": None, "meta": {}, "errors": {"code": "NOT_FOUND"}})

    def _validate(self, request, body, token):
        intent_id = str(uuid.uuid4())
        high_impact = body["intent"]["action"] in HIGH_IMPACT
        value = {
            "intent_id": intent_id, "status": "validated", "requested_by": token,
            "idempotency_key": request.headers.get("Idempotency-Key") if self.store_key else "other-key",
            "validation": {"simulation_required": high_impact if self.lab else True},
            "approval_binding": {"plan_hash": "a" * 64, "binding_digest": "b" * 64, "run_id": str(uuid.UUID(int=9))}
            if self.lab else None,
            "simulation_action_binding": {"intent_id": intent_id, "plan_sha256": "a" * 64,
                                          "network_state_sha256": "c" * 64} if self.lab else None,
        }
        self.intents[intent_id] = value
        return _envelope(value)

    def _start(self, body):
        config = ScenarioConfig.model_validate(body["scenario_config"]).model_dump(mode="json")
        simulation_id = str(uuid.uuid4())
        self.simulations[simulation_id] = {"config": config, "network_id": body["network_id"], "polls": 0}
        return _envelope({"simulation_id": simulation_id, "state": "queued"}, status=202)

    def _simulation(self, simulation_id):
        record = self.simulations[simulation_id]
        record["polls"] += 1
        done = record["polls"] > self.polls_before_completion
        compliant = limits_respect_policy(record["config"]["limits"], policy_floors(get_settings()))
        return _envelope({"simulation_id": simulation_id, "state": "completed" if done else "running",
                          "risk_gate": "passed" if done and self.simulation_passes else "blocked",
                          "execution_policy": {"limits_respect_policy": compliant}})

    def _execute(self, body, token):
        intent = self.intents[body["intent_id"]]

        def conflict(code):
            return _envelope(errors={"code": code, "message": code}, status=409)

        if body.get("cancel"):
            if body.get("idempotency_key") not in (None, intent["idempotency_key"]):
                return conflict("INTENT_IDEMPOTENCY_CONFLICT")
            return _envelope({"intent_id": body["intent_id"], "status": "execution_started"}, status=202)
        if body.get("idempotency_key") not in (None, intent["idempotency_key"]):
            return conflict("INTENT_IDEMPOTENCY_CONFLICT")
        if not self.lab:
            return _envelope({"intent_id": body["intent_id"], "status": "execution_started"}, status=202)
        if body.get("manual_approval") is not True:
            return conflict("MANUAL_APPROVAL_REQUIRED")
        if token == intent["requested_by"]:
            return conflict("DISTINCT_APPROVER_REQUIRED")
        if intent["validation"]["simulation_required"]:
            evidence = self.simulations.get(body.get("simulation_id") or "")
            if evidence is None:
                return conflict("SIMULATION_REQUIRED")
            if evidence["config"]["action_binding"] != intent["simulation_action_binding"]:
                return conflict("SIMULATION_EVIDENCE_REJECTED")
        if body.get("approval_binding") != intent["approval_binding"]:
            return conflict("APPROVAL_BINDING_MISMATCH")
        execution = self.executions.setdefault(body["intent_id"], {"body": body, "approver": token})
        if execution["body"] != body:
            return conflict("INTENT_IDEMPOTENCY_CONFLICT")
        return _envelope({"intent_id": body["intent_id"], "status": "execution_started",
                          "execution_provenance": {"execution_id": "e-" + body["intent_id"],
                                                   "approved_by_user_id": token}}, status=202)

    def paths(self, method=None):
        return [path for verb, path, _, _ in self.calls if method in (None, verb)]


def _clients(api: FakeIntentApi):
    transport = httpx.MockTransport(api.handler)
    requester = httpx.AsyncClient(transport=transport, base_url="http://api", headers={"Authorization": REQUESTER})
    approver = httpx.AsyncClient(transport=transport, base_url="http://api", headers={"Authorization": APPROVER})
    return requester, approver


def _flow(requester, approver, **kwargs):
    return ApprovalFlow(requester=requester, approver=approver, workspace_id=WORKSPACE, network_id=NETWORK,
                        execution_mode="emulation", simulation_timeout=5, **kwargs)


# Pure helpers --------------------------------------------------------------------

def test_policy_scenario_passes_its_limits_and_respects_the_default_floors():
    binding = {"intent_id": str(uuid.uuid4()), "plan_sha256": "a" * 64, "network_state_sha256": "b" * 64}
    raw = policy_scenario_config(binding)
    raw["action_binding"]["intent_id"] = "mutated"
    assert binding["intent_id"] != "mutated"  # copied, never aliased
    config = ScenarioConfig.model_validate(policy_scenario_config(binding))
    assert config.action_binding.model_dump(mode="json") == binding
    checkpoint = initial_checkpoint(config)
    while checkpoint["state"]["tick"] < config.duration_ticks:
        checkpoint = advance(config, checkpoint, ticks=32)
    result = output(config, checkpoint)
    assert result["risk_gate"] == "passed" and result["loss_pct"] == 0
    assert limits_respect_policy(config.limits.model_dump(), policy_floors(get_settings()))


def test_policy_limits_follow_configured_floors():
    assert policy_limits() == POLICY_LIMITS
    assert limits_respect_policy(policy_limits(get_settings()), policy_floors(get_settings()))
    strict = get_settings().model_copy(update={"SIMULATION_POLICY_MAX_LOSS_PCT": 0.25,
                                               "SIMULATION_POLICY_MAX_LATENCY_MS": 200.0,
                                               "SIMULATION_POLICY_MIN_THROUGHPUT_MBPS": 0.2})
    limits = policy_limits(strict)
    assert limits == {"max_loss_pct": 0.25, "max_latency_ms": 200.0, "min_throughput_mbps": 0.2}
    assert limits_respect_policy(limits, policy_floors(strict))


def test_execute_body_reuses_the_stored_key_and_echoes_the_approval_binding():
    validated = {"intent_id": "i", "idempotency_key": "stored", "approval_binding": {"plan_hash": "p"}}
    body = execute_body(validated, workspace_id=WORKSPACE, simulation_id=uuid.UUID(int=5))
    assert body == {"workspace_id": WORKSPACE, "intent_id": "i", "manual_approval": True, "idempotency_key": "stored",
                    "approval_binding": {"plan_hash": "p"}, "simulation_id": str(uuid.UUID(int=5))}
    assert "idempotency_key" not in execute_body({"intent_id": "i"}, workspace_id=WORKSPACE)
    assert execute_body({"intent_id": "i"}, workspace_id=WORKSPACE, cancel=True)["cancel"] is True


@pytest.mark.parametrize(("intent", "required"), [
    ({"validation": {"simulation_required": True}, "simulation_action_binding": {"intent_id": "i"}}, True),
    ({"validation_result": {"simulation_required": True}, "simulation_action_binding": {"intent_id": "i"}}, True),
    ({"validation": {"simulation_required": True}, "simulation_action_binding": None}, False),  # not bindable
    ({"validation": {"simulation_required": False}, "simulation_action_binding": {"intent_id": "i"}}, False),
    ({}, False),
])
def test_requires_simulation_only_when_required_and_bindable(intent, required):
    assert requires_simulation(intent) is required


# Approval flow (verify_execution / verify_operator_override) --------------------------

async def test_high_impact_sequence_validates_simulates_then_distinct_approver_executes():
    api = FakeIntentApi()
    requester, approver = _clients(api)
    async with requester, approver:
        flow = _flow(requester, approver, limits=policy_limits(get_settings()))
        validated = await flow.validate(intent_payload("reroute"))
        accepted = await flow.execute(validated["intent_id"])
    assert accepted["execution_provenance"]["approved_by_user_id"] == APPROVER
    methods = [(verb, path.split("/")[3], token) for verb, path, token, _ in api.calls]
    assert methods[0] == ("POST", "intents", REQUESTER)
    assert methods[1] == ("POST", "simulations", APPROVER) and methods[-1] == ("POST", "intents", APPROVER)
    assert all(call == ("GET", "simulations", APPROVER) for call in methods[2:-1]) and len(methods) >= 4
    started = api.calls[1][3]
    assert started["network_id"] == NETWORK
    assert started["scenario_config"]["action_binding"] == validated["simulation_action_binding"]
    assert started["scenario_config"]["limits"] == policy_limits(get_settings())
    execute = api.calls[-1][3]
    assert execute["idempotency_key"] == validated["idempotency_key"]
    assert execute["approval_binding"] == validated["approval_binding"]
    assert execute["simulation_id"] in api.simulations and execute["manual_approval"] is True


async def test_validate_sends_a_fresh_idempotency_key_each_time():
    api = FakeIntentApi()
    requester, approver = _clients(api)
    async with requester, approver:
        flow = _flow(requester, approver)
        first = await flow.validate(intent_payload("restore"))
        second = await flow.validate(intent_payload("restore"))
    keys = [first["idempotency_key"], second["idempotency_key"]]
    assert len(set(keys)) == 2 and all(key.startswith("verify-") and len(key) <= 120 for key in keys)


async def test_concurrent_duplicate_approvals_share_one_simulation_and_one_body():
    api = FakeIntentApi(polls_before_completion=3)
    requester, approver = _clients(api)
    async with requester, approver:
        flow = _flow(requester, approver)
        intent_id = (await flow.validate(intent_payload("multipath")))["intent_id"]
        results = await asyncio.gather(*(flow.execute(intent_id) for _ in range(4)))
    assert api.paths("POST").count("/api/v1/simulations/start") == 1
    bodies = [body for verb, path, _, body in api.calls if path == "/api/v1/intents/execute"]
    assert len(bodies) == 4 and all(body == bodies[0] for body in bodies)
    assert {row["execution_provenance"]["execution_id"] for row in results} == {"e-" + intent_id}


async def test_non_high_impact_actions_execute_without_simulation():
    api = FakeIntentApi()
    requester, approver = _clients(api)
    async with requester, approver:
        flow = _flow(requester, approver)
        intent_id = (await flow.validate(intent_payload("shape", dscp=10)))["intent_id"]
        await flow.execute(intent_id)
    assert "/api/v1/simulations/start" not in api.paths()
    assert "simulation_id" not in api.calls[-1][3]


async def test_rejections_are_returned_for_the_verifiers_negative_checks():
    api = FakeIntentApi()
    requester, approver = _clients(api)
    async with requester, approver:
        flow = _flow(requester, approver)
        intent_id = (await flow.validate(intent_payload("reroute")))["intent_id"]
        own = await flow.execute(intent_id, actor=requester, expected=409)
        from scripts.verify_execution import api_data

        unsimulated = await api_data(approver, "POST", "/api/v1/intents/execute", expected=409,
                                     json=flow.body(intent_id))
        unbound = flow.body(intent_id, simulation_id=await flow.evidence(intent_id))
        unbound.pop("approval_binding")
        mismatch = await api_data(approver, "POST", "/api/v1/intents/execute", expected=409, json=unbound)
        with pytest.raises(VerificationError, match="HTTP contract failed"):
            await flow.execute(intent_id, actor=requester)  # expected 202 but rejected
    assert (own["code"], unsimulated["code"], mismatch["code"]) == (
        "DISTINCT_APPROVER_REQUIRED", "SIMULATION_REQUIRED", "APPROVAL_BINDING_MISMATCH")
    assert api.executions == {}
    assert api.paths("POST").count("/api/v1/simulations/start") == 1  # evidence reused


async def test_cancel_uses_only_the_stored_key():
    api = FakeIntentApi()
    requester, approver = _clients(api)
    async with requester, approver:
        flow = _flow(requester, approver)
        validated = await flow.validate(intent_payload("reroute"))
        await flow.cancel(validated["intent_id"])
    body = api.calls[-1][3]
    assert body == {"workspace_id": WORKSPACE, "intent_id": validated["intent_id"], "manual_approval": False,
                    "cancel": True, "idempotency_key": validated["idempotency_key"]}
    assert "/api/v1/simulations/start" not in api.paths()


async def test_failing_evidence_stops_before_execution():
    api = FakeIntentApi(simulation_passes=False)
    requester, approver = _clients(api)
    async with requester, approver:
        flow = _flow(requester, approver)
        intent_id = (await flow.validate(intent_payload("reroute")))["intent_id"]
        with pytest.raises(VerificationError, match="did not pass"):
            await flow.execute(intent_id)
    assert "/api/v1/intents/execute" not in api.paths()


async def test_evidence_with_limits_weaker_than_the_floors_is_refused():
    api = FakeIntentApi()
    requester, approver = _clients(api)
    async with requester, approver:
        binding = (await _flow(requester, approver).validate(intent_payload("reroute")))["simulation_action_binding"]
        weak = {**POLICY_LIMITS, "max_loss_pct": 100.0}
        with pytest.raises(VerificationError, match="weaker than the server policy floors"):
            await run_bound_simulation(approver, network_id=NETWORK, limits=weak, action_binding=binding)
    assert "/api/v1/intents/execute" not in api.paths()


async def test_validate_that_does_not_store_the_key_is_rejected():
    api = FakeIntentApi(store_key=False)
    requester, approver = _clients(api)
    async with requester, approver:
        with pytest.raises(VerificationError, match="idempotency key"):
            await _flow(requester, approver).validate(intent_payload("reroute"))


# Strathmore demo (sync NanfoApiClient) ---------------------------------------------------

@pytest.fixture
def strathmore_api(monkeypatch):
    def install(api: FakeIntentApi):
        real_client = httpx.Client
        monkeypatch.setattr(strathmore.httpx, "Client",
                            lambda **kwargs: real_client(transport=httpx.MockTransport(api.handler), **kwargs))
        return api
    return install


def _strathmore_args(**overrides):
    args = strathmore._build_parser().parse_args([])
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def _validated(client, *, action):
    return client.validate_intent(workspace_id=WORKSPACE, network_id=NETWORK, idempotency_key="strathmore-validate-1",
                                  intent_payload={"action": action})


def test_strathmore_demo_mode_executes_with_the_stored_validate_key(strathmore_api, monkeypatch):
    monkeypatch.delenv("NANFO_APPROVER_EMAIL", raising=False)
    api = strathmore_api(FakeIntentApi(lab=False))
    args = _strathmore_args(approver_email="")
    with strathmore.NanfoApiClient(base_url="http://api") as client:
        client.login(email="requester@example.com", password="pw")
        validated = _validated(client, action="optimize_wireless_capacity")
        strathmore._execute_validated_intent(client, args, org_id="org", workspace_id=WORKSPACE, network_id=NETWORK,
                                             validated=validated, validate_idempotency_key="strathmore-validate-1")
    method, path, token, body = api.calls[-1]
    assert (method, path, token) == ("POST", "/api/v1/intents/execute", "Bearer requester-token")
    assert body == {"workspace_id": WORKSPACE, "intent_id": validated["intent_id"],
                    "idempotency_key": "strathmore-validate-1"}  # never a new "-execute-" key
    assert "/api/v1/simulations/start" not in api.paths()


def test_strathmore_lab_mode_uses_a_distinct_seeded_approver_with_binding_and_evidence(strathmore_api):
    api = strathmore_api(FakeIntentApi(lab=True))
    args = _strathmore_args(approver_email="approver@example.com", approver_password="pw2",
                            simulation_timeout_seconds=5.0)
    with strathmore.NanfoApiClient(base_url="http://api") as client:
        client.login(email="requester@example.com", password="pw")
        validated = _validated(client, action="reroute_path")
        accepted = strathmore._execute_validated_intent(
            client, args, org_id="org", workspace_id=WORKSPACE, network_id=NETWORK, validated=validated,
            validate_idempotency_key="strathmore-validate-1")
    assert accepted["execution_provenance"]["approved_by_user_id"] == APPROVER
    assert api.members == [{"token": "Bearer requester-token", "user_id": "approver-user", "org_role": "Operator"}]
    started = next(body for verb, path, _, body in api.calls if path == "/api/v1/simulations/start")
    assert started["scenario_config"]["action_binding"] == validated["simulation_action_binding"]
    body = api.calls[-1][3]
    assert api.calls[-1][2] == APPROVER
    assert body["idempotency_key"] == "strathmore-validate-1" and body["manual_approval"] is True
    assert body["approval_binding"] == validated["approval_binding"] and body["simulation_id"] in api.simulations


def test_strathmore_lab_mode_without_approver_surfaces_the_four_eyes_rejection(strathmore_api):
    strathmore_api(FakeIntentApi(lab=True))
    args = _strathmore_args(approver_email="", simulation_timeout_seconds=5.0)
    with strathmore.NanfoApiClient(base_url="http://api") as client:
        client.login(email="requester@example.com", password="pw")
        validated = _validated(client, action="optimize_wireless_capacity")
        with pytest.raises(strathmore.NanfoApiError, match="DISTINCT_APPROVER_REQUIRED"):
            strathmore._execute_validated_intent(client, args, org_id="org", workspace_id=WORKSPACE,
                                                 network_id=NETWORK, validated=validated,
                                                 validate_idempotency_key="strathmore-validate-1")


def test_strathmore_parser_adds_optional_approver_settings(monkeypatch):
    monkeypatch.setenv("NANFO_APPROVER_EMAIL", "ops@example.com")
    monkeypatch.setenv("NANFO_APPROVER_PASSWORD", "secret")
    args = strathmore._build_parser().parse_args([])
    assert (args.approver_email, args.approver_password, args.simulation_timeout_seconds) == (
        "ops@example.com", "secret", 60.0)
    assert args.idempotency_prefix == "strathmore-demo"  # existing CLI unchanged
