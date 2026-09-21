"""Explicit protected/hash-pinned operator installation; never an API input."""

import hashlib
import importlib
import importlib.util
import inspect
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from app.modules.autonomy.artifact_io import ArtifactStore, parse_json
from app.modules.autonomy.registry import protected_path
from app.modules.autonomy.schemas import SHA256

from .ports import Ports
from .schemas import ExperimentalPolicy, Record


class Installation(Record):
    version: Literal["nanfo.experimental-installation/v1"]
    policy: ExperimentalPolicy
    factory: str = Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_.]*:[a-zA-Z_][a-zA-Z0-9_]*$")
    factory_sha256: SHA256
    source_pins: dict[str, SHA256] = Field(min_length=1)
    options: dict[str, Any]

    async def build_ports(self):
        # Verify declared dependency bytes before importing executable adapters.
        for name, digest in self.source_pins.items():
            path = Path(name)
            if not path.is_absolute():
                raise ValueError("experimental_source_pin_not_absolute")
            protected_path(path)
            ArtifactStore(str(path.parent)).read(path.name, sha256=digest)
        module_name, function_name = self.factory.split(":")
        spec = importlib.util.find_spec(module_name)
        if spec is None or not spec.origin:
            raise ValueError("experimental_factory_missing")
        path = Path(spec.origin)
        protected_path(path)
        content = ArtifactStore(str(path.parent)).read(path.name, sha256=self.factory_sha256)
        if self.source_pins.get(str(path)) != hashlib.sha256(content).hexdigest():
            raise ValueError("experimental_factory_not_source_pinned")
        factory = getattr(importlib.import_module(module_name), function_name)
        ports = factory(policy=self.policy, options=self.options)
        if inspect.isawaitable(ports):
            ports = await ports
        if not isinstance(ports, Ports):
            raise ValueError("experimental_factory_ports_invalid")
        for adapter, methods in ((ports.observer, ("observe",)), (ports.model, ("infer",)),
                                 (ports.simulator, ("simulate",)),
                                 (ports.transport, ("prepare", "execute", "verify", "recover"))):
            if any(not inspect.iscoroutinefunction(getattr(adapter, method, None)) for method in methods):
                raise ValueError("experimental_factory_async_protocol_required")
        return ports


def load_installation(path=None, expected_sha256=None):
    path = path or os.environ.get("NANFO_EXPERIMENTAL_CONFIG")
    expected_sha256 = expected_sha256 or os.environ.get("NANFO_EXPERIMENTAL_CONFIG_SHA256")
    if not path or not expected_sha256 or not Path(path).is_absolute():
        raise ValueError("experimental_protected_configuration_required")
    path = Path(path)
    protected_path(path)
    return Installation.model_validate(parse_json(ArtifactStore(str(path.parent)).read(
        path.name, sha256=expected_sha256, limit=1024 * 1024)))
