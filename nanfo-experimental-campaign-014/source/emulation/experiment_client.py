"""One bounded ADR-011 JSON request on stdin, one response on stdout."""

import json
import math
import socket
import sys

SOCKET = "/run/nanfo/experiment.sock"
REQUEST_LIMIT = 4096
RESPONSE_LIMIT = 1024 * 1024


def decode(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON field")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("Nonfinite JSON number")

    def number(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("Nonfinite JSON number")
        return result

    try:
        return json.loads(
            data, object_pairs_hook=pairs, parse_constant=constant, parse_float=number
        )
    except RecursionError as error:
        raise ValueError("JSON nesting exceeds parser limit") from error


def exchange(value):
    data = json.dumps(value, allow_nan=False).encode("ascii")
    if len(data) > REQUEST_LIMIT:
        raise ValueError("Request exceeds 4096 bytes")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(60)
        client.connect(SOCKET)
        client.sendall(data)
        client.shutdown(socket.SHUT_WR)
        response = bytearray()
        while len(response) <= RESPONSE_LIMIT:
            part = client.recv(65536)
            if not part:
                return decode(response)
            response.extend(part)
        raise ValueError("Response exceeds 1 MiB")


def main():
    try:
        data = sys.stdin.buffer.read(REQUEST_LIMIT + 1)
        if len(data) > REQUEST_LIMIT:
            raise ValueError("Request exceeds 4096 bytes")
        result = exchange(decode(data))
    except (OSError, ValueError, TypeError) as error:
        result = {"version": 1, "ok": False, "error": str(error)[:200], "data": None}
    print(json.dumps(result, allow_nan=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
