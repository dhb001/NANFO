"""Alert tenancy: recorded scope columns and the authorized list scope (ADR-028).

Alert rows record their tenancy in the Alert-owned ``org_id``/``workspace_id``/
``network_id`` columns, derived from the recorded payload scope exactly as the
per-row authorization reads it (top-level value first, else the nested
``scope`` object). The payload remains the immutable evidence; the columns are
an indexed projection of it. Rows whose columns are all NULL (unscoped, invalid
or written before the columns existed) are matched by the legacy JSON predicate
and still re-verified in memory against the recorded payload.

Platform-scoped alerts (ADR-028, Telemetry runtime-adapter SLO): a payload with
``alert_scope: "platform"`` and no recorded workspace is never tenant-visible;
only global Admins (unscoped tokens) list and read it.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

SCOPE_KEYS = ("org_id", "workspace_id", "network_id")
PLATFORM_ALERT_SCOPE = "platform"


class InvalidAlertScope(ValueError):
    """A recorded scope value is present but is not a UUID (fails closed)."""


def recorded_scope_value(payload: Mapping[str, Any] | None, key: str) -> uuid.UUID | None:
    """Return the recorded scope UUID for ``key`` or raise :class:`InvalidAlertScope`.

    Mirrors the historical per-row authorization: a non-null top-level value wins,
    otherwise the nested ``scope`` object's value is used.
    """
    if not isinstance(payload, Mapping):
        return None
    raw = payload.get(key)
    if raw is None:
        nested = payload.get("scope")
        if isinstance(nested, Mapping):
            raw = nested.get(key)
    if raw is None:
        return None
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError, AttributeError):
        raise InvalidAlertScope(key) from None


def scope_columns(payload: Mapping[str, Any] | None) -> dict[str, uuid.UUID | None]:
    """Tenancy column values for a payload.

    All-or-nothing: when any present scope value is not a UUID every column stays
    NULL, so the fail-closed legacy predicate (not a partial column scope) governs
    the row.
    """
    try:
        return {key: recorded_scope_value(payload, key) for key in SCOPE_KEYS}
    except InvalidAlertScope:
        return dict.fromkeys(SCOPE_KEYS)


def is_platform_scoped(payload: Mapping[str, Any] | None) -> bool:
    """``alert_scope == "platform"`` (top level) and no recorded workspace.

    An invalid recorded workspace is not "no workspace" (fails closed). Recorded
    network/org values do not make a platform alert tenant-visible.
    """
    if not isinstance(payload, Mapping) or payload.get("alert_scope") != PLATFORM_ALERT_SCOPE:
        return False
    try:
        return recorded_scope_value(payload, "workspace_id") is None
    except InvalidAlertScope:
        return False


@dataclass(frozen=True)
class AlertListScope:
    """Authorized list scope resolved from live owner memberships.

    ``workspace_orgs`` maps every authorized workspace to its organization.
    ``member_org_ids`` authorizes org-only records (empty whenever a workspace
    or network narrows the request). ``networks`` maps network ids known to
    belong to an authorized workspace (selected network, legacy network-only
    scopes and networks verified after the query) to their workspace.
    ``network_id`` is a validated network selection. ``platform`` authorizes
    platform-scoped alerts (global Admin, unscoped token, no selection).
    """

    workspace_orgs: Mapping[uuid.UUID, uuid.UUID] = field(default_factory=dict)
    member_org_ids: frozenset[uuid.UUID] = frozenset()
    networks: Mapping[uuid.UUID, uuid.UUID] = field(default_factory=dict)
    network_id: uuid.UUID | None = None
    platform: bool = False

    @property
    def empty(self) -> bool:
        return not self.workspace_orgs and not self.member_org_ids and not self.platform

    def allows(self, payload: Mapping[str, Any] | None) -> bool:
        """Exact in-memory authorization of a recorded payload (no I/O).

        Equivalent to the per-row owner checks for the authority captured in this
        scope: network rows need a known network inside an authorized workspace and
        a matching recorded workspace/org; workspace rows need an authorized
        workspace and matching org; org-only rows need live org membership;
        platform-scoped rows need platform authority and no network selection.
        """
        if is_platform_scoped(payload):
            return self.platform and self.network_id is None
        try:
            network_id = recorded_scope_value(payload, "network_id")
            workspace_id = recorded_scope_value(payload, "workspace_id")
            org_id = recorded_scope_value(payload, "org_id")
        except InvalidAlertScope:
            return False
        if self.network_id is not None and network_id != self.network_id:
            return False
        if network_id is not None:
            network_workspace = self.networks.get(network_id)
            if network_workspace is None or network_workspace not in self.workspace_orgs:
                return False
            if workspace_id is not None and workspace_id != network_workspace:
                return False
            return org_id is None or self.workspace_orgs[network_workspace] == org_id
        if workspace_id is not None:
            workspace_org = self.workspace_orgs.get(workspace_id)
            return workspace_org is not None and (org_id is None or workspace_org == org_id)
        return org_id is not None and org_id in self.member_org_ids
