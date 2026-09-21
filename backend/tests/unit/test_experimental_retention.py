"""Exact recognized locator grammar, no arbitrary UUID or snapshot hash guessing."""

import json
from uuid import uuid4

import pytest

from app.modules.autonomy.experimental.models import LabAction, LabReceipt, LabRun
from app.modules.autonomy.experimental.references import experimental_telemetry_references, policy_scope
from app.modules.autonomy.experimental.schemas import contract_digest


def test_nested_recognized_locators_and_unrelated_identifiers():
    ids = [uuid4() for _ in range(5)]
    scope = uuid4(), uuid4()
    row = LabReceipt(receipt_id=uuid4(), run_id=uuid4(), payload={
        "observation": {"samples": [{"record_id": str(ids[0])}], "evidence": [f"telemetry_record:{ids[1]}"]},
        "raw": {"source_record_ids": [str(ids[2])]},
        "observation_json": json.dumps({"telemetry_record_id": str(ids[3])}),
        "snapshot_id": str(ids[4]), "run_id": str(ids[4]), "sha256": "a" * 64})
    item = experimental_telemetry_references(row, scope=scope)
    assert {ref.record_id for ref in item.references} == set(ids[:4])
    assert {ref.network_id for ref in item.references} == {scope[1]}
    assert experimental_telemetry_references(row, scope=scope) == item


@pytest.mark.parametrize("field", ["frame", "inference", "simulation", "command", "prepared"])
def test_every_persisted_action_field_has_version_bound_reference(field):
    record = uuid4()
    scope = uuid4(), uuid4()
    row = LabAction(request_id=uuid4(), run_id=uuid4(), **{field: {"record_id": str(record)}})
    before = experimental_telemetry_references(row, scope=scope)
    assert before.references[0].record_id == record
    setattr(row, field, {"record_id": str(record), "evidence_version": 2})
    assert experimental_telemetry_references(row, scope=scope).references[0].reference_id != before.references[0].reference_id


def test_run_policy_scope_integrity_and_malformed_locator_fail_closed():
    workspace, network = uuid4(), uuid4()
    policy = {"workspace_id": str(workspace), "network_id": str(network), "record_id": str(uuid4())}
    row = LabRun(run_id=uuid4(), policy=policy, policy_sha256=contract_digest(policy))
    assert experimental_telemetry_references(row).references[0].network_id == network
    with pytest.raises(ValueError, match="policy_invalid"):
        policy_scope(policy, "0" * 64)
    with pytest.raises(ValueError):
        experimental_telemetry_references(LabReceipt(receipt_id=uuid4(), payload={"record_id": "invalid"}),
                                           scope=(workspace, network))
