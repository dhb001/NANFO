"""Standalone opt-in deployment settings; the parent owns application composition."""

import os
from dataclasses import dataclass
from pathlib import Path

from app.modules.autonomy.artifact_io import EvidenceError

CONFIG_KEYS = ("NANFO_LIVE_MODEL_REGISTRY", "NANFO_LIVE_MODEL_REGISTRY_SHA256",
               "NANFO_MODEL_ROOT", "NANFO_MODEL_PYTHON", "NANFO_LIVE_OBSERVATION_ROOT")


@dataclass(frozen=True)
class LiveSettings:
    registry_path: str
    registry_sha256: str
    artifact_root: str
    interpreter: str
    observation_root: str

    @classmethod
    def configured(cls):
        # Partial configuration is an installed-but-invalid provider, not a silent fallback.
        return any(os.environ.get(key) for key in (CONFIG_KEYS[0], CONFIG_KEYS[1], CONFIG_KEYS[4]))

    @classmethod
    def from_environment(cls):
        values = [os.environ.get(key, "") for key in CONFIG_KEYS]
        if not all(values):
            raise EvidenceError("live_provider_configuration_incomplete")
        if any(not Path(values[index]).is_absolute() for index in (0, 2, 3, 4)):
            raise EvidenceError("live_provider_paths_not_absolute")
        return cls(*values)

    def environment(self):
        return dict(zip(CONFIG_KEYS, (self.registry_path, self.registry_sha256, self.artifact_root,
                                      self.interpreter, self.observation_root), strict=True))
