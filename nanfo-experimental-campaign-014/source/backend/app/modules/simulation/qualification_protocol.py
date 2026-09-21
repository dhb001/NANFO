"""ADR023 immutable, externally preregistered raw acquisition import protocol.

The artifact store is a public read-only contract; no Autonomy state is accessed.
An attestation hash must be pinned out of band: an identity string is not auth.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.modules.autonomy.artifact_io import (
    SHA256, ArtifactRef, ArtifactStore, EvidenceError, StrictEvidence, parse_json,
)

Name = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")]
Amount = Annotated[float, Field(ge=0, le=1e15)]
Positive = Annotated[float, Field(gt=0, le=1e15)]


class CaptureGroup(StrictEvidence):
    group_id: Name
    split: Literal["train", "holdout"]
    sample_ids: list[Name] = Field(min_length=1, max_length=1000)


class AcquisitionProtocol(StrictEvidence):
    schema_version: Literal["nanfo.independent-protocol.v1"]
    campaign_id: Name
    dataset_id: Name
    domain: Literal["rf", "network"]
    environment: Literal["synthetic", "isolated-emulation", "physical-network"]
    network_id: Name
    run_id: Name
    declared_at_unix_seconds: Amount
    configuration: ArtifactRef
    acquisition_recipe: ArtifactRef | None = None
    # Group IDs denote whole independent sessions/sites/runs, not individual rows.
    group_basis: str = Field(min_length=20, max_length=2000)
    groups: list[CaptureGroup] = Field(min_length=2, max_length=100)
    instrument_ids: list[Name] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_split(self):
        ids = [key for group in self.groups for key in group.sample_ids]
        if (len(ids) != len(set(ids)) or len(ids) > 10000
                or len({g.group_id for g in self.groups}) != len(self.groups)
                or {g.split for g in self.groups} != {"train", "holdout"}
                or len(set(self.instrument_ids)) != len(self.instrument_ids)):
            raise ValueError("duplicate_or_incomplete_preregistered_split")
        return self


class RawRecord(StrictEvidence):
    sample_id: Name
    source_record_id: Name
    instrument_id: Name
    observed_at_unix_seconds: Amount
    measurement: dict


class RawCapture(StrictEvidence):
    schema_version: Literal["nanfo.raw-capture.v1"]
    protocol_sha256: SHA256
    dataset_id: Name
    group_id: Name
    environment: Literal["synthetic", "isolated-emulation", "physical-network"]
    # Original instrument/collector output, never a model prediction artifact.
    native_sources: list[ArtifactRef] = Field(min_length=1, max_length=100)
    records: list[RawRecord] = Field(min_length=1, max_length=1000)


class InstrumentRecord(StrictEvidence):
    source_record_id: Name
    observed_at_unix_seconds: Amount
    measurement: dict


class InstrumentExport(StrictEvidence):
    schema_version: Literal["nanfo.instrument-records.v1"]
    instrument_id: Name
    records: list[InstrumentRecord] = Field(min_length=1, max_length=1000)


class MeasurementAttestation(StrictEvidence):
    schema_version: Literal["nanfo.measurement-attestation.v1"]
    protocol_sha256: SHA256
    dataset_id: Name
    operator_id: Name
    method: Literal["operator-attested", "authenticated-instrument"]
    identity_evidence: ArtifactRef
    instrument_ids: list[Name] = Field(min_length=1, max_length=100)
    capture_sha256: list[SHA256] = Field(min_length=2, max_length=100)
    attested_at_unix_seconds: Amount
    statement: Literal["I attest these original measurements, identities, units, coordinates and complete capture groups; no fabricated or omitted observations."]


class CampaignManifest(StrictEvidence):
    schema_version: Literal["nanfo.independent-campaign.v1"]
    protocol: ArtifactRef
    captures: list[ArtifactRef] = Field(min_length=2, max_length=100)
    attestation: ArtifactRef


class ImportedCampaign(StrictEvidence):
    protocol: AcquisitionProtocol
    protocol_sha256: SHA256
    campaign_sha256: SHA256
    configuration: dict
    captures: list[RawCapture]
    attestation_sha256: SHA256
    attested_at_unix_seconds: Amount

    def records(self, split: str):
        groups = {g.group_id for g in self.protocol.groups if g.split == split}
        return [r for c in self.captures if c.group_id in groups for r in c.records]


def import_campaign(
    store: ArtifactStore, manifest: ArtifactRef, *,
    trusted_preregistrations: dict[str, float], trusted_attesters: set[str],
) -> ImportedCampaign:
    """Validate exact raw bytes and external receipts; never infer authenticity."""
    body = store.referenced(manifest)
    dossier = CampaignManifest.model_validate(parse_json(body))
    protocol = AcquisitionProtocol.model_validate(parse_json(store.referenced(dossier.protocol)))
    registered = trusted_preregistrations.get(dossier.protocol.sha256)
    if (type(registered) not in (int, float) or not 0 <= registered <= 1e15
            or registered < protocol.declared_at_unix_seconds):
        raise EvidenceError("protocol_not_externally_preregistered")
    if dossier.attestation.sha256 not in trusted_attesters:
        raise EvidenceError("measurement_attestation_not_trusted")
    att = MeasurementAttestation.model_validate(parse_json(store.referenced(dossier.attestation)))
    if (att.protocol_sha256 != dossier.protocol.sha256 or att.dataset_id != protocol.dataset_id
            or set(att.instrument_ids) != set(protocol.instrument_ids)
            or len(att.instrument_ids) != len(set(att.instrument_ids))
            or sorted(att.capture_sha256) != sorted(r.sha256 for r in dossier.captures)
            or len(set(att.capture_sha256)) != len(att.capture_sha256)):
        raise EvidenceError("attestation_scope_mismatch")
    # Identity evidence is protected-channel receipt, device certificate or operator
    # signed record. Only external review of the pinned attestation confers trust.
    store.referenced(att.identity_evidence)
    config = parse_json(store.referenced(protocol.configuration))
    recipe = None
    if protocol.acquisition_recipe is not None:
        from app.modules.simulation.qualification_acquisition import LocalAcquisitionRecipe

        recipe = LocalAcquisitionRecipe.model_validate(parse_json(store.referenced(protocol.acquisition_recipe)))
        if protocol.environment != "isolated-emulation" or protocol.domain != "network":
            raise EvidenceError("local_acquisition_cannot_qualify_physical_environment")
    groups = {g.group_id: g for g in protocol.groups}
    captures, seen_groups, seen_records, seen_observations, native_hashes = [], set(), set(), set(), set()
    total = 0
    for ref in dossier.captures:
        capture = RawCapture.model_validate(parse_json(store.referenced(ref)))
        group = groups.get(capture.group_id)
        if (group is None or capture.group_id in seen_groups
                or capture.protocol_sha256 != dossier.protocol.sha256
                or capture.dataset_id != protocol.dataset_id
                or capture.environment != protocol.environment
                or sorted(r.sample_id for r in capture.records) != sorted(group.sample_ids)):
            raise EvidenceError("capture_scope_or_sample_coverage_mismatch")
        seen_groups.add(capture.group_id)
        source_records, local_events = {}, {}
        for native in capture.native_sources:
            total += native.size_bytes
            if total > 64 * 1024 * 1024:
                raise EvidenceError("campaign_native_bytes_exceeded")
            if native.sha256 in native_hashes:
                raise EvidenceError("reused_native_capture_group")
            native_hashes.add(native.sha256)
            content = store.referenced(native, limit=64 * 1024 * 1024)
            # Instrument export is the exact original record stream. Supplemental
            # vendor logs/certificates can be arbitrary bytes, retained by hash.
            try:
                document = parse_json(content)
            except EvidenceError:
                continue
            if isinstance(document, dict) and document.get("schema_version") == "nanfo.instrument-records.v1":
                export = InstrumentExport.model_validate(document)
                for row in export.records:
                    key = export.instrument_id, row.source_record_id
                    if key in source_records:
                        raise EvidenceError("duplicate_instrument_source_record")
                    source_records[key] = row
            elif isinstance(document, dict) and document.get("schema_version") == "nanfo.loopback-events.v1":
                if (recipe is None or protocol.environment != "isolated-emulation"
                        or document.get("collector_sha256") != recipe.collector_sha256):
                    raise EvidenceError("local_acquisition_identity_or_environment_mismatch")
                timestamp = document.get("start_unix_seconds")
                if type(timestamp) not in (int, float) or timestamp in local_events:
                    raise EvidenceError("duplicate_native_event_window")
                local_events[timestamp] = document
        verify_local = bool(local_events) or protocol.acquisition_recipe is not None
        for record in capture.records:
            identity = (record.instrument_id, record.source_record_id)
            source = source_records.pop(identity, None)
            if (source is None or source.observed_at_unix_seconds != record.observed_at_unix_seconds
                    or source.measurement != record.measurement):
                raise EvidenceError("raw_instrument_record_mismatch")
            if verify_local:
                from app.modules.simulation.qualification_acquisition import verify_native_events

                native = local_events.pop(record.observed_at_unix_seconds, None)
                if native is None:
                    raise EvidenceError("native_acquisition_window_missing")
                verify_native_events(native, record.measurement)
                declared = next((w for w in recipe.windows if w.sample_id == record.sample_id), None)
                if (declared is None or record.instrument_id != recipe.instrument_id
                        or record.measurement.get("action_id") != declared.action_id
                        or record.measurement.get("previous_action_id") != declared.previous_action_id):
                    raise EvidenceError("local_acquisition_recipe_mismatch")
            observation = (record.instrument_id, record.observed_at_unix_seconds)
            if identity in seen_records or observation in seen_observations:
                raise EvidenceError("duplicate_raw_measurement")
            if (record.instrument_id not in protocol.instrument_ids
                    or not registered < record.observed_at_unix_seconds <= att.attested_at_unix_seconds):
                raise EvidenceError("measurement_identity_or_preregistration_mismatch")
            seen_records.add(identity)
            seen_observations.add(observation)
        if source_records or local_events:
            raise EvidenceError("omitted_instrument_observations")
        captures.append(capture)
    if seen_groups != set(groups):
        raise EvidenceError("capture_groups_incomplete")
    return ImportedCampaign(
        protocol=protocol, protocol_sha256=dossier.protocol.sha256,
        campaign_sha256=hashlib.sha256(body).hexdigest(), configuration=config,
        captures=captures, attestation_sha256=dossier.attestation.sha256,
        attested_at_unix_seconds=att.attested_at_unix_seconds,
    )
