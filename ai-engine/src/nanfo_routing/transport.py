"""Bounded argv-only transport to an operator-selected, fixed lab container."""

import json
import os
import re
import selectors
import subprocess
import time
from dataclasses import dataclass
from typing import Protocol

from .contracts import Request

MAX_RESPONSE_BYTES = 256 * 1024


class TransportError(RuntimeError):
    pass


class Transport(Protocol):
    def exchange(self, request: Request) -> dict: ...


@dataclass(frozen=True)
class DockerTransport:
    container: str = "nanfo-emulation-lab-1"
    timeout: float = 90.0

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", self.container):
            raise ValueError("invalid fixed container name")
        if not 15 <= self.timeout <= 180:
            raise ValueError("transport timeout must be 15..180 seconds")

    def exchange(self, request: Request) -> dict:
        argv = ["docker", "exec", "-i", self.container,
                "python", "-m", "emulation.experiment_client"]
        try:
            with subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, shell=False) as process:
                try:
                    process.stdin.write(request.model_dump_json().encode() + b"\n")
                    process.stdin.close()
                    output = {"stdout": bytearray(), "stderr": bytearray()}
                    deadline = time.monotonic() + self.timeout
                    with selectors.DefaultSelector() as selector:
                        for name in output:
                            selector.register(getattr(process, name), selectors.EVENT_READ, name)
                        while selector.get_map():
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                raise TransportError("experiment transport timeout; state uncertain")
                            for key, _ in selector.select(min(remaining, 0.2)):
                                chunk = os.read(key.fd, 8192)
                                if not chunk:
                                    selector.unregister(key.fileobj)
                                else:
                                    output[key.data].extend(chunk)
                                    if len(output[key.data]) > MAX_RESPONSE_BYTES:
                                        raise TransportError("experiment output exceeds bound")
                    process.wait(timeout=max(0.01, deadline - time.monotonic()))
                    if process.returncode:
                        raise TransportError("experiment client failed; consult container logs")
                except BaseException:
                    process.kill()
                    process.wait()
                    raise
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TransportError("experiment client unavailable or timed out") from exc
        try:
            result = json.loads(output["stdout"])
            if type(result) is not dict:
                raise ValueError("object required")
            return result
        except (ValueError, UnicodeError) as exc:
            raise TransportError("experiment client returned invalid JSON") from exc
