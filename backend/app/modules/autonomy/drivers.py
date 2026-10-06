"""Capability-driven autonomous runtime/driver registry (ADR-028 BE-Autonomy fix 7).

Core execution and installation code never compares runtime or driver identifiers
with brand names. Each runtime *profile* is declared by its own driver module (OVS in
``ovs_runtime``, FRR in ``frr_installation``) and states which capabilities an
installation of that runtime requires; a driver provides capabilities either by
declaring ``capabilities`` or through its public interface (``dispatch_guard``).
Unknown runtimes fail closed.
"""

from __future__ import annotations

import importlib
import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Capability(StrEnum):
    #: The driver exposes an independent async ``dispatch_guard(authorization)`` that the
    #: receiver authority re-runs before every dispatch step.
    INDEPENDENT_DISPATCH_GUARD = "independent_dispatch_guard"
    #: Executable plans are bound to separately reviewed runtime evidence that must be
    #: independently validated at installation load.
    RUNTIME_BINDING = "runtime_binding"


#: Capabilities a *driver object* must provide (the rest are installation-level).
DRIVER_CAPABILITIES = frozenset({Capability.INDEPENDENT_DISPATCH_GUARD})


@dataclass(frozen=True)
class RuntimeProfile:
    runtime_id: str
    #: Plan contract class accepted for this runtime's installed actions.
    plan_type: type
    requires: frozenset[Capability] = frozenset()
    #: Plan fields bound to installed runtime evidence; ignored when comparing a plan with the
    #: independently reviewed (evidence-free) plan.
    plan_binding_fields: frozenset[str] = frozenset()
    #: ``(installation_data, evidence, **runtime_trust) -> binding`` for RUNTIME_BINDING runtimes.
    validate_runtime_binding: Callable[..., Any] | None = None
    #: ``(lab, *, resource_id, run_id, ownership_check) -> driver`` for in-process lab composition.
    lab_driver_factory: Callable[..., Any] | None = None

    def needs(self, capability: Capability) -> bool:
        return capability in self.requires


#: Driver modules declaring the built-in profiles; imported lazily on first lookup.
PROFILE_MODULES = ("app.modules.autonomy.ovs_runtime", "app.modules.autonomy.frr_installation")
_PROFILES: dict[str, RuntimeProfile] = {}
_LOAD_LOCK = threading.Lock()
_loaded = False


def register_runtime(profile: RuntimeProfile) -> RuntimeProfile:
    existing = _PROFILES.get(profile.runtime_id)
    if existing is not None and existing != profile:
        raise ValueError("autonomous_runtime_profile_conflict")
    _PROFILES[profile.runtime_id] = profile
    return profile


def _load_builtin_profiles() -> None:
    global _loaded
    if _loaded:
        return
    with _LOAD_LOCK:
        if not _loaded:
            for module in PROFILE_MODULES:
                importlib.import_module(module)
            _loaded = True


def runtime_profile(runtime_id) -> RuntimeProfile:
    _load_builtin_profiles()
    try:
        return _PROFILES[runtime_id]
    except KeyError:
        raise ValueError("autonomous_runtime_profile_unregistered") from None


def driver_capabilities(driver) -> frozenset[Capability]:
    declared = getattr(driver, "capabilities", None)
    if declared is not None:
        return frozenset(Capability(value) for value in declared)
    provided = set()
    if callable(getattr(driver, "dispatch_guard", None)):
        provided.add(Capability.INDEPENDENT_DISPATCH_GUARD)
    return frozenset(provided)


def bind_driver(driver, installation_data) -> RuntimeProfile:
    """The driver implements the installed runtime and provides every required driver capability."""
    profile = runtime_profile(installation_data.runtime_action)
    if getattr(driver, "driver_id", None) != profile.runtime_id:
        raise ValueError("installed_lab_driver_scope_mismatch")
    missing = (profile.requires & DRIVER_CAPABILITIES) - driver_capabilities(driver)
    if missing:
        raise ValueError("driver_capability_missing:" + ",".join(sorted(missing)))
    return profile
