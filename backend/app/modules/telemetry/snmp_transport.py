"""Bounded SNMPv3 authPriv GET via net-snmp; no shell, SET, WALK or fallback."""

from __future__ import annotations

import asyncio
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.modules.telemetry.snmp_config import InterfaceBinding, SNMPBinding, SNMPCredentials, SNMPError

SYS_UPTIME = ".1.3.6.1.2.1.1.3.0"
SYS_NAME = ".1.3.6.1.2.1.1.5.0"
ENGINE_BOOTS = ".1.3.6.1.6.3.10.2.1.2.0"
IF_COLUMNS = {
    "if_index": (".1.3.6.1.2.1.2.2.1.1", "INTEGER", 2**31 - 1),
    "if_name": (".1.3.6.1.2.1.31.1.1.1.1", "STRING", 128),
    "rx": (".1.3.6.1.2.1.31.1.1.1.6", "Counter64", 2**64 - 1),
    "tx": (".1.3.6.1.2.1.31.1.1.1.10", "Counter64", 2**64 - 1),
    "speed": (".1.3.6.1.2.1.2.2.1.5", "Gauge32", 2**32 - 1),
    "high_speed": (".1.3.6.1.2.1.31.1.1.1.15", "Gauge32", 2**32 - 1),
    "discontinuity": (".1.3.6.1.2.1.31.1.1.1.19", "Timeticks", 2**32 - 1),
}
MAX_OUTPUT_BYTES = 16384


def requested_oids(interface: InterfaceBinding) -> tuple[str, ...]:
    return (SYS_UPTIME, SYS_NAME, ENGINE_BOOTS, *(f"{oid}.{interface.if_index}" for oid, _, _ in IF_COLUMNS.values()))


@dataclass(frozen=True)
class InterfaceCounters:
    uptime: int
    engine_boots: int
    rx: int
    tx: int
    speed_bps: int
    discontinuity: int
    speed_oid: str


def parse_response(data: bytes, binding: SNMPBinding, interface: InterfaceBinding) -> InterfaceCounters:
    """Parse numeric-OID, typed net-snmp -One output, matching every varbind."""
    try:
        if len(data) > MAX_OUTPUT_BYTES:
            raise ValueError
        values = {}
        for line in data.decode("ascii").splitlines():
            match = re.fullmatch(r"(\.[0-9.]+) = ([A-Za-z0-9]+): (.+)", line)
            if match is None or match[1] in values:
                raise ValueError
            values[match[1]] = (match[2], match[3])
        if set(values) != set(requested_oids(interface)):
            raise ValueError

        def read(oid, kind, maximum):
            actual_kind, raw = values[oid]
            if actual_kind != kind:
                raise ValueError
            if kind == "STRING":
                text = raw[1:-1] if raw.startswith('"') and raw.endswith('"') else raw
                if not 1 <= len(text) <= maximum:
                    raise ValueError
                return text
            # Keep the ASN.1 type: -Ot suppresses the TimeTicks type label on
            # net-snmp builds. Extract the exact ticks from normal typed output.
            if kind == "Timeticks":
                ticks = re.fullmatch(r"\(([0-9]{1,10})\) [0-9a-zA-Z:., ]+", raw)
                if ticks is None:
                    raise ValueError
                raw = ticks[1]
            if not re.fullmatch(r"[0-9]{1,20}", raw) or int(raw) > maximum:
                raise ValueError
            return int(raw)

        if read(SYS_NAME, "STRING", 253) != binding.sys_name:
            raise ValueError
        fields = {name: read(f"{oid}.{interface.if_index}", kind, maximum)
                  for name, (oid, kind, maximum) in IF_COLUMNS.items()}
        if fields["if_index"] != interface.if_index or fields["if_name"] != interface.if_name:
            raise ValueError
        # ifSpeed is more precise below its saturation value. ifHighSpeed is Mbps.
        speed = fields["speed"]
        speed_oid = IF_COLUMNS["speed"][0]
        if speed == 2**32 - 1:
            speed = fields["high_speed"] * 1_000_000
            speed_oid = IF_COLUMNS["high_speed"][0]
        return InterfaceCounters(
            uptime=read(SYS_UPTIME, "Timeticks", 2**32 - 1),
            engine_boots=read(ENGINE_BOOTS, "INTEGER", 2**31 - 1),
            rx=fields["rx"], tx=fields["tx"], speed_bps=speed,
            discontinuity=fields["discontinuity"], speed_oid=f"{speed_oid}.{interface.if_index}",
        )
    except (ValueError, KeyError, UnicodeError):
        raise SNMPError("invalid_or_incomplete_snmp_response") from None


class NetSNMPTransport:
    def __init__(self, *, credentials_path: Path, executable: Path = Path("/usr/bin/snmpget")):
        self.credentials_path = credentials_path
        self.executable = executable

    def check_available(self) -> None:
        try:
            info = self.executable.lstat()
            if (not self.executable.is_absolute() or self.executable.name != "snmpget"
                    or not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022
                    or info.st_uid not in {0, os.geteuid()} or not os.access(self.executable, os.X_OK)):
                raise ValueError
        except (OSError, ValueError):
            raise SNMPError("net_snmp_unavailable_or_unsafe") from None

    async def get(self, binding: SNMPBinding, interface: InterfaceBinding) -> InterfaceCounters:
        from app.modules.telemetry.snmp_config import load_protected_json

        self.check_available()
        credentials = load_protected_json(self.credentials_path, SNMPCredentials)
        with tempfile.TemporaryDirectory(prefix="nanfo-snmp-") as temporary:
            directory = Path(temporary)
            # Debian Net-SNMP initializes this under SNMP_PERSISTENT_DIR even
            # with persistence disabled, logging directory creation to stderr.
            # Provision it privately before exec; retain strict stderr rejection.
            (directory / "cert_indexes").mkdir(mode=0o700)
            config = directory / "snmp.conf"
            fd = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as stream:
                stream.write(
                    "defVersion 3\ndefSecurityLevel authPriv\n"
                    f"defSecurityName {credentials.username.get_secret_value()}\n"
                    f"defAuthType {credentials.auth_protocol}\n"
                    f"defPrivType {credentials.priv_protocol}\n"
                    f"defAuthPassphrase {credentials.auth_passphrase.get_secret_value()}\n"
                    f"defPrivPassphrase {credentials.priv_passphrase.get_secret_value()}\n"
                    "doDebugging 0\ndumpPacket no\nnoPersistentLoad yes\nnoPersistentSave yes\n"
                )
            # Isolate all configuration and persistent state from system/user
            # defaults. No secrets are put in argv or environment values.
            env = {"LC_ALL": "C", "HOME": temporary, "SNMPCONFPATH": temporary,
                   "SNMP_PERSISTENT_DIR": temporary, "MIBS": "", "MIBDIRS": temporary}
            target = (f"udp6:[{binding.target}]:{binding.port}" if binding.target.version == 6
                      else f"udp:{binding.target}:{binding.port}")
            args = [str(self.executable), "-v", "3", "-l", "authPriv", "-One", "-m", "",
                    "-r", "0", "-t", str(binding.timeout_seconds), target, *requested_oids(interface)]
            data = await self._execute(args, env, temporary, binding.timeout_seconds + 1)
        return parse_response(data, binding, interface)

    @staticmethod
    async def _execute(args: list[str], env: dict[str, str], cwd: str, timeout: float) -> bytes:
        process = None
        tasks = []

        async def bounded_read(stream):
            result = bytearray()
            while chunk := await stream.read(4096):
                result.extend(chunk)
                if len(result) > MAX_OUTPUT_BYTES:
                    raise SNMPError("snmp_output_limit")
            return bytes(result)

        try:
            process = await asyncio.create_subprocess_exec(
                *args, env=env, cwd=cwd, stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                limit=MAX_OUTPUT_BYTES,
            )
            tasks = [asyncio.create_task(bounded_read(process.stdout)),
                     asyncio.create_task(bounded_read(process.stderr)),
                     asyncio.create_task(process.wait())]
            async with asyncio.timeout(timeout):
                stdout, stderr, code = await asyncio.gather(*tasks)
            # stderr may contain credentials echoed by a library config error.
            # Never include either stream or process exceptions in diagnostics.
            if code != 0 or stderr:
                raise SNMPError("snmp_request_failed")
            return stdout
        except TimeoutError:
            raise SNMPError("snmp_timeout") from None
        except OSError:
            raise SNMPError("snmp_process_unavailable") from None
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if process is not None and process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            if process is not None:
                # A killed child with a full asyncio pipe can leave wait()
                # blocked until EOF is consumed. Drain without retaining bytes.
                async def discard(stream):
                    while await stream.read(4096):
                        pass

                await asyncio.gather(discard(process.stdout), discard(process.stderr), process.wait())
