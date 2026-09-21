"""v2 integration with test-only evidence/provider state. No live lab or trust."""

import hashlib
import json

import pytest

from app.modules.autonomy.calibration_verification import LoadedCalibration, runtime_uncertainty_floor
from app.modules.autonomy.calibration_verification_models import CalibrationScope, NetworkQualificationConfig
from app.modules.autonomy.execution_contract import AutonomousCommand
from app.modules.autonomy.safety_installation import IndependentInstallationValidator, validate_execution_binding
from app.modules.autonomy.safety_provider import CalibratedSafetyProvider, SafetyInstallation, ValidatedInstallation
from app.modules.autonomy.schemas import canonical_json, contract_digest
from tests.autonomous_execution_support import fixture


def v2(*, available=False):
    f = fixture()
    data = f.installation.data.model_dump(mode="json")
    config = json.loads(f.installation.reviewed_configuration)
    source = dict(path="test-source.json", sha256="e" * 64, size_bytes=1)
    data.update(version="nanfo.calibrated-safety/v2", min_dt_seconds=.125, service_semantics_evidence=source)
    data["evidence"].append(source)
    config.update(schema_version="nanfo.network-qualification-config.v2", min_dt_seconds=.125,
                  service_semantics_evidence=source)
    for action, reviewed in zip(data["actions"], config["actions"]):
        for queue, bound in zip(action["queues"], reviewed["bounds"]):
            new = dict(service_lower_semantics="busy-period-available" if available else "actual-departures",
                       service_upper_burst_bytes=10. if queue["egress_id"] == "a" else 20.,
                       shaper_nominal_bytes_per_second=25.)
            queue.update(new)
            bound.update(new)
    config = NetworkQualificationConfig.model_validate_json(json.dumps(config))
    data["calibration"]["min_service_uncertainty_bytes_per_second"] = runtime_uncertainty_floor(config)
    data["evidence"].append(dict(path="calibration.json", sha256="d" * 64, size_bytes=1))
    content = json.dumps(data).encode()
    installed = ValidatedInstallation(content, hashlib.sha256(content).hexdigest(), config.model_dump_json().encode())
    provider = CalibratedSafetyProvider(None, installed)
    scope = CalibrationScope(network_id=str(installed.data.network_id), run_id=installed.data.calibration.run_id,
        provider_id=config.provider_id, environment="isolated-emulation", configuration_sha256=data["configuration_sha256"],
        egress_ids=config.egress_ids, demand_ids=config.demand_ids,
        action_ids=[a.action_id for a in config.actions], max_dt_seconds=config.dt_seconds,
        max_delay_seconds=config.max_delay_seconds)
    loaded = LoadedCalibration(installed.data.calibration, scope, "d" * 64, False, config)
    return f, installed, provider, loaded


def evaluate(f, provider):
    return provider.evaluate(f.observation, f.proposal, f.safety.binding.observation, f.safety.binding.state,
                             now=f.observation.observed_at.timestamp())


def command(f, installed, result):
    auth = f.auth.model_copy(update=dict(safety_evidence_json=canonical_json(result),
        selected_action_json=canonical_json(result.selected_action), safety_sha256=contract_digest(result),
        selected_action_sha256=contract_digest(result.selected_action),
        certificate_expires_at_unix_seconds=result.certificate.expires_at_unix_seconds))
    return AutonomousCommand.model_validate({**f.command.model_dump(), "authorization": auth,
                                             "installation_sha256": installed.sha256})


def test_v2_installation_provider_and_receiver_share_exact_burst_horizon_mapping():
    f, installed, provider, loaded = v2()
    assert IndependentInstallationValidator(loaded).validate(installed.data, {}, sha256=installed.sha256) == installed.sha256
    result = evaluate(f, provider)
    assert result.admissible
    rates = {q.egress_id: q.service_upper_bytes_per_second for q in result.selected_action.bounds.queues}
    assert rates == {"a": 35., "b": 45.}
    assert all(q.capacity_bytes_per_second == 100 for q in result.binding.observation.queues)
    assert all(q.service_upper_bytes_per_second == 25 for q in installed.data.actions[0].queues)
    assert result.binding.policy == f.safety.binding.policy
    loaded.validate_action(result.selected_action, configuration_sha256=loaded.scope.configuration_sha256,
        route_egress_ids={p.route_id: p.egress_ids for p in installed.data.policy.allowed_paths},
        previous_action_id="baseline", now=f.observation.observed_at.timestamp())
    command(f, installed, result).validate_installed_service(installed)


def test_available_lower_service_maps_to_zero_and_unchanged_drift_can_refuse():
    f, installed, provider, loaded = v2(available=True)
    IndependentInstallationValidator(loaded).validate(installed.data, {}, sha256=installed.sha256)
    assert installed.service_bounds(installed.data.actions[0].queues[0], 1.) == (0., 35.)
    assert not evaluate(f, provider).admissible  # no budget change to force success
    assert installed.data.policy == f.installation.data.policy


@pytest.mark.parametrize("horizon", [.0625, .125, .5, 2.])
def test_receiver_rejects_shorter_or_longer_than_installed_horizon(horizon):
    f, installed, provider, loaded = v2()
    result = evaluate(f, provider)
    action = result.selected_action.model_copy(deep=True)
    action.bounds.dt_seconds = horizon
    with pytest.raises(ValueError, match="horizon"):
        loaded.validate_action(action, configuration_sha256=loaded.scope.configuration_sha256,
            route_egress_ids={p.route_id: p.egress_ids for p in installed.data.policy.allowed_paths},
            previous_action_id="baseline", now=f.observation.observed_at.timestamp())


@pytest.mark.parametrize("field,value", [("service_upper_bytes_per_second", 25.), ("service_lower_bytes_per_second", 0.)])
def test_receiver_rejects_nominal_or_mutated_mapped_bound(field, value):
    f, installed, provider, loaded = v2()
    action = evaluate(f, provider).selected_action.model_copy(deep=True)
    setattr(action.bounds.queues[0], field, value)
    with pytest.raises(ValueError, match="bounds_differ"):
        loaded.validate_action(action, configuration_sha256=loaded.scope.configuration_sha256,
            route_egress_ids={p.route_id: p.egress_ids for p in installed.data.policy.allowed_paths},
            previous_action_id="baseline", now=f.observation.observed_at.timestamp())


@pytest.mark.parametrize("mutation", ["burst", "capacity", "nominal", "source", "minimum", "budget", "uncertainty", "version"])
def test_installation_and_every_provider_read_refuse_altered_source_profiles(mutation):
    f, installed, provider, loaded = v2()
    data = installed.data.model_dump(mode="json")
    if mutation in {"burst", "capacity", "nominal"}:
        key = {"burst": "service_upper_burst_bytes", "capacity": "capacity_bytes_per_second",
               "nominal": "shaper_nominal_bytes_per_second"}[mutation]
        data["actions"][0]["queues"][0][key] += 1
    elif mutation == "source":
        data["service_semantics_evidence"]["sha256"] = "f" * 64
    elif mutation == "minimum":
        data["min_dt_seconds"] = .0625
    elif mutation == "budget":
        data["policy"]["drift_budget_bytes_squared"] += 1
    elif mutation == "uncertainty":
        data["calibration"]["min_service_uncertainty_bytes_per_second"] = 0.
    else:
        data["version"] = "nanfo.calibrated-safety/v1"
    with pytest.raises(ValueError):
        validate_execution_binding(SafetyInstallation.model_validate(data), loaded.configuration)


def test_v1_manifest_and_configuration_shapes_preserved():
    f = fixture()
    original = json.loads(f.installation.content)
    serialized = f.installation.data.model_dump(mode="json")
    assert serialized == {**original, "runtime_binding": None}
    assert "min_dt_seconds" not in serialized
    assert "service_upper_burst_bytes" not in serialized["actions"][0]["queues"][0]
    config = NetworkQualificationConfig.model_validate_json(f.installation.reviewed_configuration)
    assert "min_dt_seconds" not in config.model_dump()
    assert "service_lower_semantics" not in config.model_dump()["actions"][0]["bounds"][0]


def test_upper_mapping_saturates_at_real_physical_cap_without_mutating_it():
    _, installed, _, loaded = v2()
    bound = loaded.configuration.actions[0].bounds[0].model_copy(update={"service_upper_burst_bytes": 1000.})
    from app.modules.autonomy.calibration_verification import runtime_service_bounds
    assert runtime_service_bounds(loaded.configuration, bound, 1.) == (20., 100.)
    assert bound.capacity_bytes_per_second == 100


def test_v2_calibration_loader_source_trust_is_still_external(tmp_path, monkeypatch):
    from app.modules.autonomy import calibration_verification as verifier
    from tests.unit.test_independent_validation import installation
    from tests.unit.test_native_qualification_review import v2_campaign

    store, args = installation(tmp_path)
    campaign, trust = v2_campaign(tmp_path)
    monkeypatch.setattr(verifier, "import_campaign", lambda *_args, **_kwargs: campaign)
    with pytest.raises(ValueError, match="service_semantics_review_required"):
        verifier.load_trusted_calibration(store, "installation.json", **args)
    loaded = verifier.load_trusted_calibration(store, "installation.json", **args,
        accepted_service_semantics_sha256=trust["accepted_service_semantics_sha256"])
    assert loaded.configuration.schema_version.endswith(".v2")


def test_v2_installation_busy_profile_fails_conservative_runtime_drift(tmp_path, monkeypatch):
    from app.modules.autonomy import calibration_verification as verifier
    from tests.unit.test_independent_validation import installation
    from tests.unit.test_native_qualification_review import v2_campaign, busy_evidence

    store, args = installation(tmp_path)
    campaign, trust = v2_campaign(tmp_path)
    campaign.configuration["actions"][0]["bounds"][0]["service_lower_semantics"] = "busy-period-available"
    accepted = busy_evidence(tmp_path, campaign)
    monkeypatch.setattr(verifier, "import_campaign", lambda *_args, **_kwargs: campaign)
    with pytest.raises(ValueError, match="conservative_runtime_network_validation_failed"):
        verifier.load_trusted_calibration(store, "installation.json", **args,
            accepted_service_semantics_sha256=trust["accepted_service_semantics_sha256"],
            accepted_native_backlog_sha256=accepted)


def test_provider_evaluation_rejects_tampered_nominal_even_after_rehashing_installation():
    f, installed, _, _ = v2()
    data = installed.data.model_dump(mode="json")
    data["actions"][0]["queues"][0]["service_upper_burst_bytes"] = 0.
    content = json.dumps(data).encode()
    tampered = ValidatedInstallation(content, hashlib.sha256(content).hexdigest(), installed.reviewed_configuration)
    with pytest.raises(ValueError, match="original_service_profile"):
        evaluate(f, CalibratedSafetyProvider(None, tampered))


def test_rehashed_wire_action_with_short_horizon_refuses_before_mutation():
    f, installed, provider, _ = v2()
    result = evaluate(f, provider)
    result.selected_action.bounds.dt_seconds = .0625
    altered = command(f, installed, result)
    with pytest.raises(ValueError, match="service_horizon"):
        altered.validate_installed_service(installed)


def test_expired_dispatch_does_not_change_recovery_contract():
    f, installed, provider, _ = v2()
    result = evaluate(f, provider)
    recovery = command(f, installed, result).model_copy(update={"operation": "recover"})
    # The read-only guard does not mint/extend expiry or require fresh requester
    # permission; recovery_checkpoint itself remains ownership-only.
    recovery.validate_installed_service(installed)
    assert recovery.authorization == command(f, installed, result).authorization


@pytest.mark.asyncio
async def test_real_receiver_checkpoint_invokes_v2_wire_guard_before_authority_or_mutation():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.modules.autonomy.execution import ReceiverJournal

    f, installed, provider, _ = v2()
    result = evaluate(f, provider)
    result.selected_action.bounds.dt_seconds = .0625
    altered = command(f, installed, result)
    db = AsyncMock()
    context = AsyncMock()
    context.__aenter__.return_value = db
    authority = SimpleNamespace(safety=provider, check=AsyncMock())
    journal = ReceiverJournal(lambda: context, authority, altered, "test-token")
    with pytest.raises(ValueError, match="service_horizon"):
        await journal.checkpoint(altered, mutation=True)
    authority.check.assert_not_called()
    db.flush.assert_not_called()


def test_empty_new_trust_sets_do_not_change_existing_config_serialization():
    # Build only serializer fixtures without installation or environment access.
    from app.modules.autonomy.execution_settings import ExecutionClientConfig
    from scripts.autonomous_frr_receiver import ReceiverConfig

    for cls in (ExecutionClientConfig, ReceiverConfig):
        value = cls.model_construct(accepted_service_semantics_sha256=set(), accepted_native_backlog_sha256=set())
        dumped = value.model_dump(warnings=False)
        assert "accepted_service_semantics_sha256" not in dumped
        assert "accepted_native_backlog_sha256" not in dumped
