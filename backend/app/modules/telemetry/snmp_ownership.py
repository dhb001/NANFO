"""Measured collector composition using existing Identity/Network public services.

Authorization cost model (ADR-028):

- The *full* owner check (actor permissions, write membership, device scope and
  active inventory address) runs once per batch: a fresh boundary (or
  ``invalidate()``) starts every batch, and results are cached for a short TTL
  keyed by the pinned binding revision (sha256) and write/read intent.
- Every further call (each interface GET and each sample publication) performs
  only the cheap checks: the protected binding file still has the same revision
  and the actor is still an active identity (single primary-key lookup through
  ``IdentityDirectoryService``). Membership/permission/inventory revocation is
  observed at the next batch or TTL expiry, whichever comes first.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from ipaddress import ip_address
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.core.logging import get_logger
from app.modules.identity.service import AuthService, IdentityDirectoryService
from app.modules.network.service import NetworkService
from app.modules.telemetry.diagnostics import OWNER_BOUNDARY_FAILURES, FailureCounter
from app.modules.telemetry.snmp_config import ProtectedRevision, SNMPBinding, SNMPError, binding_sha256

logger = get_logger(__name__)

AUTHORITY_TTL_SECONDS = 10.0


async def validate_owner_scope(binding: SNMPBinding, *, publish: bool, identity: AuthService,
                               network: NetworkService) -> None:
    """No cross-module repositories/SQL; require active inventory and exact IP.

    The bound device is read with Network's public owner read (``get_device_for_owner``,
    ADR-028): one authorized lookup instead of paging the network's inventory.
    """
    profile = await identity.get_profile(str(binding.actor_user_id))
    required = {"read:telemetry", "read:topology"}
    if publish:
        required.add("write:config")
    if not required.issubset(profile.permissions):
        raise SNMPError("collector_permission_denied")
    await network.assert_network_workspace_access(
        network_id=binding.network_id, requested_workspace_id=binding.workspace_id,
        actor_user_id=str(binding.actor_user_id), claim_org_id=binding.org_id, require_write=publish,
    )
    scope = await network.assert_device_workspace_access(
        device_id=binding.device_id, requested_workspace_id=binding.workspace_id,
        actor_user_id=str(binding.actor_user_id), claim_org_id=binding.org_id,
    )
    if scope != (binding.network_id, binding.workspace_id):
        raise SNMPError("device_scope_mismatch")
    try:
        device = await network.get_device_for_owner(
            device_id=binding.device_id, network_id=binding.network_id, actor_user_id=str(binding.actor_user_id),
            requested_workspace_id=binding.workspace_id, claim_org_id=binding.org_id,
        )
    except HTTPException as exc:
        if exc.status_code == 404:  # absent, deleted or foreign: fail closed (stable diagnostic code)
            raise SNMPError("device_missing_or_inventory_limit") from None
        raise  # authorization outcomes keep their own classification
    try:
        matches = device.ip_address is not None and ip_address(device.ip_address) == binding.target
    except ValueError:
        matches = False
    if (device.device_id != binding.device_id or device.status != "active"
            or device.network_id != binding.network_id or not matches):
        raise SNMPError("device_inventory_binding_mismatch")


def _unavailable_code(exc: BaseException) -> str:
    if isinstance(exc, HTTPException):
        return "owner_authorization_denied"
    if isinstance(exc, (SQLAlchemyError, OSError, TimeoutError, ConnectionError)):
        return "owner_authorization_unavailable"
    return "owner_authorization_failed"


class SNMPOwnerBoundary:
    def __init__(self, *, binding_path: Path, session_factory, redis,
                 authority_ttl_seconds: float = AUTHORITY_TTL_SECONDS,
                 clock: Callable[[], float] = time.monotonic,
                 failures: FailureCounter | None = None):
        self.binding_path = binding_path
        self.session_factory = session_factory
        self.redis = redis
        self.authority_ttl_seconds = max(0.0, float(authority_ttl_seconds))
        self._clock = clock
        self._failures = failures or OWNER_BOUNDARY_FAILURES
        self._authorized: dict[tuple[str, bool], float] = {}
        self._binding_revision = ProtectedRevision(binding_path, SNMPBinding)
        self.full_checks = 0

    def invalidate(self) -> None:
        """Start a new batch: the next call performs the full owner check."""
        self._authorized.clear()

    def _cached(self, revision: str, publish: bool, now: float) -> bool:
        # Write authority implies read authority for the same binding revision.
        keys = [(revision, True)] if publish else [(revision, False), (revision, True)]
        return any(self._authorized.get(key, 0.0) > now for key in keys)

    async def authorize(self, binding: SNMPBinding, publish: bool) -> None:
        if not self._binding_revision.matches(binding):  # exact version check, every call
            self.invalidate()
            raise SNMPError("binding_changed_restart_required")
        revision, now = binding_sha256(binding), self._clock()
        cached = self._cached(revision, publish, now)
        try:
            async with self.session_factory() as db:
                if cached:
                    if not await IdentityDirectoryService(db).user_exists(binding.actor_user_id):
                        raise SNMPError("collector_actor_revoked")
                    return
                self.full_checks += 1
                await validate_owner_scope(
                    binding, publish=publish, identity=AuthService(db, self.redis),
                    network=NetworkService(db, self.redis),
                )
        except SNMPError:
            self.invalidate()
            raise
        except Exception as exc:
            self.invalidate()
            self._failures.record(logger, "telemetry_owner_authorization_failed", exc,
                                  default=_unavailable_code(exc), device_id=str(binding.device_id),
                                  publish=publish, cached=cached)
            raise SNMPError("owner_authorization_failed_or_unavailable") from None
        self._authorized[(revision, publish)] = now + self.authority_ttl_seconds
