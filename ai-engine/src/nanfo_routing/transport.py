"""Bounded argv-only transport to an operator-selected, fixed lab container."""

import os
import re
import selectors
import subprocess
import time
from dataclasses import dataclass
from typing import Protocol

from .contracts import Request, parseJson

MAX_RESPONSE_BYTES = 1024 * 1024


class TransportError(RuntimeError):
    pass


class Transport(Protocol):
    def exchange(self, request: Request) -> dict: ...


@dataclass(frozen=True)
class DockerTransport:
    container: str = "nanfo-experiment"
    timeout: float = 90.0

    def __post_init__(self):
        if not re.fullmatch(r"nanfo-experiment|nanfo-training-[0-9a-f]{32}", self.container):
            raise ValueError("invalid fixed container name")
        if not 15 <= self.timeout <= 180:
            raise ValueError("transport timeout must be 15..180 seconds")

    def exchange(self, request: Request) -> dict:
        request = Request.model_validate(request.model_dump())
        encoded = request.model_dump_json().encode() + b"\n"
        if len(encoded) > 4096:
            raise ValueError("request exceeds wire bound")
        argv = [
            "docker",
            "exec",
            "-i",
            self.container,
            "python",
            "-m",
            "emulation.experiment_client",
        ]
        try:
            with subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
            ) as process:
                try:
                    process.stdin.write(encoded)
                    process.stdin.close()
                    output = {"stdout": bytearray(), "stderr": bytearray()}
                    deadline = time.monotonic() + self.timeout
                    with selectors.DefaultSelector() as selector:
                        for name in output:
                            selector.register(getattr(process, name), selectors.EVENT_READ, name)
                        while selector.get_map():
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                raise TransportError(
                                    "experiment transport timeout; state uncertain"
                                )
                            for key, _ in selector.select(min(remaining, 0.2)):
                                chunk = os.read(key.fd, 8192)
                                if not chunk:
                                    selector.unregister(key.fileobj)
                                else:
                                    output[key.data].extend(chunk)
                                    if len(output[key.data]) > MAX_RESPONSE_BYTES:
                                        raise TransportError("experiment output exceeds bound")
                    process.wait(timeout=max(0.01, deadline - time.monotonic()))
                    if process.returncode and not output["stdout"]:
                        raise TransportError("experiment client failed; consult container logs")
                except BaseException:
                    process.kill()
                    process.wait()
                    raise
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TransportError("experiment client unavailable or timed out") from exc
        try:
            result = parseJson(output["stdout"])
            if type(result) is not dict:
                raise ValueError("object required")
            # The fixed client exits 1 for a valid protocol rejection. Preserve that
            # envelope as evidence, but never accept success from a failing process.
            if process.returncode and not (
                set(result) == {"version", "ok", "error", "data"}
                and type(result["version"]) is int
                and result["version"] == 1
                and result["ok"] is False
                and type(result["error"]) is str
                and len(result["error"]) <= 2048
                and result["data"] is None
            ):
                raise ValueError("client failure without rejection envelope")
            return result
        except (ValueError, UnicodeError) as exc:
            raise TransportError("experiment client returned invalid JSON") from exc
