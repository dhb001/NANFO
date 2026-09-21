"""Separate versioned FRR runtime attestation, not historical checkpoint qualification."""

import uuid
from typing import Literal

from pydantic import Field, model_validator

from app.modules.autonomy.artifact_io import ArtifactRef
from app.modules.autonomy.schemas import SHA256, Contract
from emulation.autonomous_contract import ROUTERS, RUNTIME, action_map


class FRRPlan(Contract):
    runtime: Literal["isolated-linux-frr-host-route/v1"]
    action: int = Field(strict=True, ge=0, le=1)
    runtime_binding_sha256: SHA256


class NamespaceIdentity(Contract):
    pid: int = Field(strict=True, gt=1)
    start_ticks: int = Field(strict=True, gt=0)
    netns_inode: int = Field(strict=True, gt=0)


class FRRRuntimeBinding(Contract):
    version: Literal["nanfo.autonomous-frr-runtime/v1"]
    runtime: Literal["isolated-linux-frr-host-route/v1"]
    network_id: uuid.UUID
    workspace_id: uuid.UUID
    run_id: str = Field(min_length=1, max_length=200)
    resource_id: str = Field(pattern=r"^[a-zA-Z0-9_.:-]{1,200}$")
    provider_id: str = Field(min_length=1, max_length=200)
    configuration_sha256: SHA256
    checkpoint_sha256: SHA256
    model_contract_sha256: SHA256
    model_spec_sha256: SHA256
    qualified_image_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    receiver_image_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    frozen_sources: dict[str, SHA256] = Field(min_length=1, max_length=100)
    receiver_sources: dict[str, SHA256] = Field(min_length=1, max_length=100)
    actions: dict[str, list[str]]
    action_ids: list[str] = Field(min_length=2, max_length=2)
    baseline_action: int = Field(strict=True, ge=0, le=1)
    namespaces: dict[str, NamespaceIdentity] = Field(min_length=9, max_length=9)
    reviewed_equivalence: ArtifactRef
    valid_from: float = Field(ge=0)
    valid_until: float = Field(gt=0)

    @model_validator(mode="after")
    def matching(self):
        if (self.runtime != RUNTIME or self.actions != action_map() or len(set(self.action_ids)) != 2
                or set(self.namespaces) != {*ROUTERS, "h1", "h2", "h3", "h4"}
                or len({n.netns_inode for n in self.namespaces.values()}) != 9
                or self.valid_until <= self.valid_from):
            raise ValueError("frr_runtime_scope_mismatch")
        return self
