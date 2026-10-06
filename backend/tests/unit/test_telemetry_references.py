"""Reference scanning never raises from free-form payloads (ADR-028 fix 13)."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

from app.modules.telemetry import references
from app.modules.telemetry.references import (
    OwnerReferenceItem,
    evidence_item,
    historical_item,
    reference_ids,
    scan_references,
)

NETWORK = uuid.uuid4()


def test_deep_and_large_free_form_payloads_never_raise():
    record = uuid.uuid4()
    deep = {"telemetry_record_id": str(record)}
    for _ in range(5000):  # far beyond the old depth>30 limit and Python recursion
        deep = {"nested": [deep]}
    assert scan_references(deep).record_ids == {record}
    huge = {"blob": "x" * (3 * 1024 * 1024), "evidence": [f"telemetry_record:{record}"]}  # > 2 MiB
    item = evidence_item(identity="intent:1", network_id=NETWORK, fields={"payload": huge})
    assert [ref.record_id for ref in item.references] == [record]
    assert evidence_item(identity="deep", network_id=NETWORK, fields={"payload": deep}).references


def test_generic_record_id_with_foreign_grammar_is_not_a_telemetry_locator():
    """Simulation ValueSource.record_id / qualification names are not telemetry ids."""
    payload = {"sources": {"capacity_mbps": {"kind": "measured", "record_id": "rec-17"}},
               "rows": [{"source_record_id": "qual/sample-3", "record_ids": ["a", None, {"x": 1}]}]}
    assert scan_references(payload).record_ids == set()
    assert scan_references(payload).issues == []
    assert evidence_item(identity="simulation:1", network_id=NETWORK, fields={"audit": payload}).references == []


def test_typed_locators_are_recognised_everywhere_and_malformed_ones_are_reported():
    ids = [uuid.uuid4() for _ in range(4)]
    payload = {"evidence": [f"telemetry_record:{ids[0]}", "telemetry_record:garbage"],
               "telemetry_record_ids": [str(ids[1]), "bad"],
               "samples": [{"record_id": str(ids[2])}],
               "observation_json": json.dumps({"telemetry_record_id": str(ids[3])}),
               "safety_evidence_json": "{not json"}
    scan = scan_references(payload)
    assert scan.record_ids == set(ids)
    assert sorted(scan.issues) == ["reference_locator_malformed", "reference_locator_malformed",
                                   "serialized_evidence_invalid"]


def test_strict_legacy_contract_still_fails_closed():
    record = uuid.uuid4()
    assert reference_ids({"telemetry_record_ids": [str(record)]}) == [record]
    for payload in ({"record_id": "lost-legacy-identity"}, {"telemetry_record_ids": "x"},
                    {"observation_json": {"not": "a string"}}, ["telemetry_record:bad"]):
        with pytest.raises(ValueError):
            reference_ids(payload)


def test_prospective_scan_issues_are_counted_not_raised(monkeypatch):
    logged = []
    monkeypatch.setattr(references.logger, "warning", lambda event, **fields: logged.append((event, fields)))
    before = references.REFERENCE_SCAN_ISSUES.snapshot().get("reference_locator_malformed", 0)
    item = evidence_item(identity="alert:1", network_id=NETWORK,
                         fields={"payload": {"telemetry_record_id": "not-a-uuid-secret"}})
    assert item.references == [] and item.unknown is None
    assert references.REFERENCE_SCAN_ISSUES.snapshot()["reference_locator_malformed"] == before + 1
    assert logged[-1] == ("telemetry_reference_scan_issue",
                          {"error_code": "reference_locator_malformed", "identity": "alert:1"})
    assert "secret" not in repr(logged)


def test_historical_scan_issues_and_unscoped_references_stay_unknown():
    record = uuid.uuid4()

    def malformed(row):
        return evidence_item(identity="x", network_id=NETWORK, fields={"f": {"telemetry_record_id": "bad",
                                                                              "record_id": str(record)}})

    item = historical_item(malformed, None)
    assert item.unknown == references.SCAN_UNENUMERABLE and [ref.record_id for ref in item.references] == [record]

    def unscoped(row):
        return evidence_item(identity="y", network_id=None, fields={"f": {"record_id": str(record)}})

    assert historical_item(unscoped, None).unknown == references.SCOPE_UNAVAILABLE
    prospective = unscoped(None)
    assert prospective.unknown is None and prospective._unscoped == (record,)


def test_nan_in_evidence_no_longer_fails_the_version_digest():
    record = uuid.uuid4()
    first = evidence_item(identity="sim:1", network_id=NETWORK,
                          fields={"run_output": {"record_id": str(record), "loss": float("nan")}})
    clean = evidence_item(identity="sim:1", network_id=NETWORK, fields={"run_output": {"record_id": str(record)}})
    legacy = uuid.uuid5(uuid.NAMESPACE_URL, "nanfo:sim:1:run_output:" + __import__("hashlib").sha256(
        json.dumps({"record_id": str(record)}, sort_keys=True, separators=(",", ":"), allow_nan=False)
        .encode()).hexdigest())
    assert clean.references[0].reference_id == legacy  # historical digests unchanged
    assert first.references[0].reference_id != legacy


class FakeConnection:
    pass


class FakeSession:
    def __init__(self, rows):
        self.new, self.dirty = list(rows), []
        self._connection = FakeConnection()

    def connection(self):
        return self._connection


class GuardedRow:
    def __init__(self, payload, workspace_id=None):
        self.payload, self.workspace_id = payload, workspace_id or uuid.uuid4()


@pytest.fixture
def guarded(monkeypatch):
    monkeypatch.setitem(references._GUARDS, GuardedRow, (
        "intent", lambda row: evidence_item(identity="intent:t", network_id=NETWORK, fields={"payload": row.payload}),
        lambda row: row.workspace_id, ()))
    calls = SimpleNamespace(pins=[], known=set())

    def pin(connection, *, scope, reference, skip_unknown_identity=False):
        calls.pins.append((reference.record_id, skip_unknown_identity))
        if reference.record_id in calls.known:
            return True
        if skip_unknown_identity:
            return False
        raise ValueError("Evidence record unavailable in owner scope")

    monkeypatch.setattr(references.TelemetryEvidenceService, "pin_in_transaction", staticmethod(pin))
    monkeypatch.setattr("app.modules.telemetry.pin_repository.TelemetryPinRepository.known_identity_sync",
                        staticmethod(lambda connection, record_id: record_id in calls.known))
    return calls


def test_flush_hook_skips_non_telemetry_uuid_in_free_form_payload(guarded):
    stranger, real = uuid.uuid4(), uuid.uuid4()
    guarded.known.add(real)
    row = GuardedRow({"notes": {"record_id": str(stranger)}, "evidence": [f"telemetry_record:{real}"]})
    references._pin_before_flush(FakeSession([row]), None, None)  # no exception -> no HTTP 500
    assert sorted(guarded.pins) == sorted([(stranger, True), (real, True)])


def test_flush_hook_never_raises_for_malformed_free_form_values(guarded):
    row = GuardedRow({"record_id": "rec-1", "telemetry_record_id": "bad", "x": [[[[[[{"a": 1}]]]]]]})
    references._pin_before_flush(FakeSession([row]), None, None)
    assert guarded.pins == []


def test_flush_hook_fails_closed_for_known_identity_without_scope(guarded, monkeypatch):
    real = uuid.uuid4()
    guarded.known.add(real)
    monkeypatch.setitem(references._GUARDS, GuardedRow, (
        "intent", lambda row: evidence_item(identity="i", network_id=None, fields={"p": row.payload}),
        lambda row: row.workspace_id, ()))
    with pytest.raises(ValueError, match="no network scope"):
        references._pin_before_flush(FakeSession([GuardedRow({"record_id": str(real)})]), None, None)
    # An unrelated UUID without scope is simply not telemetry evidence.
    references._pin_before_flush(FakeSession([GuardedRow({"record_id": str(uuid.uuid4())})]), None, None)


def test_owner_declared_unknown_still_fails_the_write(monkeypatch):
    monkeypatch.setitem(references._GUARDS, GuardedRow, (
        "report", lambda row: OwnerReferenceItem(identity="r", unknown="legacy_report_snapshot_unavailable"),
        lambda row: row.workspace_id, ()))
    with pytest.raises(ValueError, match="legacy_report_snapshot_unavailable"):
        references._pin_before_flush(FakeSession([GuardedRow({})]), None, None)
