"""Single vendor-neutral device-type classifier (ADR-028).

Device types are open vocabulary (Network.md §3.2). Every Network consumer that
interprets a device type — synthetic topology tiers and device-group
``functional_group`` selectors — classifies through :func:`classify_device_type`,
so the two interpretations share one normalization and one rule table and can no
longer drift apart. This module is pure: no database, graph or network I/O.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

__all__ = [
    "DEFAULT_TIER",
    "DEVICE_TYPE_TIERS",
    "FUNCTIONAL_GROUPS",
    "TIER_ACCESS",
    "TIER_CORE",
    "TIER_DISTRIBUTION",
    "TIER_LEAF",
    "TIER_ORDER",
    "TIER_PERIMETER",
    "DeviceClassification",
    "classify_device_type",
    "device_tier",
    "matches_functional_group",
    "normalize_device_type",
]

TIER_PERIMETER = "perimeter"
TIER_CORE = "core"
TIER_DISTRIBUTION = "distribution"
TIER_ACCESS = "access"
TIER_LEAF = "leaf"

#: Ordered from upstream (closest to the WAN edge) to downstream.
TIER_ORDER: tuple[str, ...] = (TIER_PERIMETER, TIER_CORE, TIER_DISTRIBUTION, TIER_ACCESS, TIER_LEAF)

#: Exact normalized ``device_type`` -> synthetic topology tier. ``switch`` is an
#: access switch because it is the least-privileged sane default.
DEVICE_TYPE_TIERS: Mapping[str, str] = {
    "firewall": TIER_PERIMETER,
    "router": TIER_CORE,
    "core_router": TIER_CORE,
    "distribution_switch": TIER_DISTRIBUTION,
    "access_switch": TIER_ACCESS,
    "switch": TIER_ACCESS,
    "wireless_ap": TIER_LEAF,
    "server": TIER_LEAF,
    "security_gateway": TIER_LEAF,
    "ups": TIER_LEAF,
    "lab_endpoint": TIER_LEAF,
}

#: Unknown device types attach at the least-privileged tier.
DEFAULT_TIER = TIER_LEAF

#: Named functional groups understood by device-group selectors. Any other
#: selector value falls back to a substring match on the normalized type.
FUNCTIONAL_GROUPS: tuple[str, ...] = ("core", "distribution", "access", "wireless", "security", "server")


@dataclass(frozen=True, slots=True)
class DeviceClassification:
    normalized: str
    tier: str
    functional_groups: frozenset[str]


def normalize_device_type(device_type: str | None) -> str:
    return device_type.strip().lower() if isinstance(device_type, str) else ""


def _functional_groups(normalized: str) -> frozenset[str]:
    if not normalized:
        return frozenset()
    rules = {
        "core": "router" in normalized or normalized == "core",
        "distribution": "distribution" in normalized or normalized == "dist",
        "access": "access" in normalized,
        "wireless": "wireless" in normalized or normalized.endswith("_ap") or normalized == "ap",
        "security": "security" in normalized or "firewall" in normalized,
        "server": "server" in normalized,
    }
    return frozenset(group for group, matched in rules.items() if matched)


def classify_device_type(device_type: str | None) -> DeviceClassification:
    """Return the one authoritative interpretation of ``device_type``."""
    normalized = normalize_device_type(device_type)
    return DeviceClassification(
        normalized=normalized,
        tier=DEVICE_TYPE_TIERS.get(normalized, DEFAULT_TIER),
        functional_groups=_functional_groups(normalized),
    )


def device_tier(device_type: str | None) -> str:
    """Map a ``device_type`` to its synthetic topology tier."""
    return classify_device_type(device_type).tier


def matches_functional_group(device_type: str | None, functional_group: str) -> bool:
    """Whether ``device_type`` belongs to a device-group ``functional_group`` selector."""
    classification = classify_device_type(device_type)
    if not classification.normalized:
        return False
    if functional_group in FUNCTIONAL_GROUPS:
        return functional_group in classification.functional_groups
    return functional_group in classification.normalized
