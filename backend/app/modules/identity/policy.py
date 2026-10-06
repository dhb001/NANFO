"""Declared global role → permission policy (ADR-026 capability table, ADR-028).

This is the single source of truth for global capabilities. The ``permissions``
table remains the seeded catalogue (migration 0001); no role/permission mapping
table exists, so authorization never queries it per request.

| Global role | Capabilities                                               |
|-------------|------------------------------------------------------------|
| Admin       | every seeded permission                                    |
| Operator    | read:topology, read:telemetry, write:config, execute:rollback |
| Read-Only   | read:topology, read:telemetry                              |

Current organization membership further restricts writes (Organization module).
"""

from __future__ import annotations

from collections.abc import Iterable
from types import MappingProxyType

# Canonical order used in tokens and profiles (stable across roles).
SEEDED_PERMISSIONS: tuple[str, ...] = (
    "read:topology",
    "read:telemetry",
    "write:config",
    "execute:rollback",
    "manage:users",
    "manage:orgs",
)

ROLE_PERMISSIONS = MappingProxyType({
    "Admin": frozenset(SEEDED_PERMISSIONS),
    "Operator": frozenset({"read:topology", "read:telemetry", "write:config", "execute:rollback"}),
    "Read-Only": frozenset({"read:topology", "read:telemetry"}),
})

KNOWN_ROLES: tuple[str, ...] = tuple(ROLE_PERMISSIONS)


def permissions_for_roles(role_names: Iterable[str]) -> list[str]:
    """Union of the declared capabilities of ``role_names`` in canonical order.

    Unknown role names contribute nothing (fail closed).
    """
    granted: set[str] = set()
    for name in role_names:
        granted |= ROLE_PERMISSIONS.get(name, frozenset())
    return [permission for permission in SEEDED_PERMISSIONS if permission in granted]


def is_capability_downgrade(before: Iterable[str], after: Iterable[str]) -> bool:
    """True when replacing roles ``before`` with ``after`` removes any role or capability.

    Role names are authorization inputs themselves (``require_roles``), so losing
    a role counts even when another retained role grants the same permissions.
    """
    before_roles, after_roles = set(before), set(after)
    if before_roles - after_roles:
        return True
    return bool(set(permissions_for_roles(before_roles)) - set(permissions_for_roles(after_roles)))
