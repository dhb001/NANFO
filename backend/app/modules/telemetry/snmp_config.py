"""ADR021 operator-owned SNMP identity and secret boundary (no device I/O)."""

from __future__ import annotations

import json
import os
import stat
import uuid
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, IPvAnyAddress, SecretStr, field_validator, model_validator

from app.modules.telemetry.emulation import reject_duplicate_keys


class SNMPError(ValueError):
    """Only fixed, credential-free diagnostic codes cross this boundary."""


class StrictConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)


class InterfaceBinding(StrictConfig):
    if_index: Annotated[int, Field(ge=1, le=2**31 - 1)]
    if_name: Annotated[str, Field(pattern=r"^[A-Za-z0-9_./:\-]{1,128}$")]


class SNMPBinding(StrictConfig):
    version: Literal[1]
    org_id: uuid.UUID
    workspace_id: uuid.UUID
    network_id: uuid.UUID
    device_id: uuid.UUID
    actor_user_id: uuid.UUID
    target: IPvAnyAddress
    port: Annotated[int, Field(ge=1, le=65535)] = 161
    sys_name: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.\-]{1,253}$")]
    interfaces: Annotated[tuple[InterfaceBinding, ...], Field(min_length=1, max_length=16)]
    execution_mode: Literal["production", "emulation"]
    environment: Literal["physical", "emulation"]
    timeout_seconds: Annotated[float, Field(ge=0.1, le=10, allow_inf_nan=False)] = 2.0
    max_interval_seconds: Annotated[float, Field(ge=1, le=3600, allow_inf_nan=False)] = 120.0
    max_pending_seconds: Annotated[float, Field(ge=1, le=300, allow_inf_nan=False)] = 30.0

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if len({i.if_index for i in self.interfaces}) != len(self.interfaces) or len(
            {i.if_name for i in self.interfaces}
        ) != len(self.interfaces):
            raise ValueError("duplicate interface binding")
        if (self.execution_mode == "production") != (self.environment == "physical"):
            raise ValueError("inconsistent measurement environment")
        if self.target.is_unspecified or self.target.is_multicast or "%" in str(self.target):
            raise ValueError("target must be a unicast IP literal without a zone")
        return self


class SNMPCredentials(StrictConfig):
    username: SecretStr
    auth_passphrase: SecretStr
    priv_passphrase: SecretStr
    auth_protocol: Literal["SHA-256", "SHA-512", "SHA"] = "SHA-256"
    priv_protocol: Literal["AES"] = "AES"

    @field_validator("username", "auth_passphrase", "priv_passphrase")
    @classmethod
    def safe_config_token(cls, value: SecretStr) -> SecretStr:
        # A deliberately restricted single-token grammar avoids net-snmp config
        # quoting, interpolation, comments, escapes and newline injection.
        import re

        if not re.fullmatch(r"[A-Za-z0-9_.@!%+=:/\-]{1,128}", value.get_secret_value()):
            raise ValueError("unsupported credential token")
        return value

    @model_validator(mode="after")
    def passphrase_lengths(self) -> Self:
        if min(len(self.auth_passphrase.get_secret_value()), len(self.priv_passphrase.get_secret_value())) < 8:
            raise ValueError("SNMPv3 passphrases must contain at least eight characters")
        if len(self.username.get_secret_value()) > 32:
            raise ValueError("USM username exceeds 32 octets")
        return self


def load_protected_json(path: Path, model: type[StrictConfig]) -> StrictConfig:
    """Read an operator/secret-manager provisioned 0600 file, without symlinks.

    Reject writable non-sticky ancestors and writable immediate parents. Opening
    relative to directory descriptors prevents final-component replacement races.
    No validation details or exception chains containing input escape this API.
    """
    directory = None
    fd = None
    try:
        path = Path(os.path.abspath(path))
        directory = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
        for component in path.parts[1:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
            info = os.fstat(directory)
            if info.st_uid not in {0, os.geteuid()} or (info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX):
                raise SNMPError("unsafe_config_directory")
        parent = os.fstat(directory)
        if parent.st_mode & 0o022:
            raise SNMPError("unsafe_config_directory")
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid not in {0, os.geteuid()} or info.st_size > 65536):
            raise SNMPError("unsafe_config_file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(65537)
        if len(data) > 65536:
            raise SNMPError("config_size_limit")
        document = json.loads(data, object_pairs_hook=reject_duplicate_keys)
        if model is SNMPBinding and type(document.get("version")) is not int:
            raise SNMPError("invalid_config")
        return model.model_validate_json(data)
    except (OSError, ValueError, TypeError, AttributeError, RecursionError):
        raise SNMPError("protected_config_invalid_or_unavailable") from None
    finally:
        if fd is not None:
            os.close(fd)
        if directory is not None:
            os.close(directory)
