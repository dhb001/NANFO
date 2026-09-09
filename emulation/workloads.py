"""Seeded workload inputs and bounded, real UDP probes (stdlib only)."""

import argparse
import json
import random
import signal
import socket
import struct
import time

SCENARIOS = ("low", "path0", "path1", "alternating", "burst", "overload")
PORT = 19110
PACKET_BYTES = 1200


def schedule(seed, scenario, decisions):
    if type(seed) is not int or not 0 <= seed <= 2147483647:
        raise ValueError("seed must be an integer in 0..2147483647")
    if scenario not in SCENARIOS or type(decisions) is not int or not 2 <= decisions <= 64:
        raise ValueError("Invalid scenario or episode length")
    rng = random.Random(seed)
    phases = []
    for index in range(decisions + 1):
        path = 1 if scenario == "path1" else index % 2 if scenario == "alternating" else 0
        foreground = rng.uniform(9, 12)
        background = rng.uniform(14, 18)
        if scenario == "low":
            foreground, background = rng.uniform(3, 5), rng.uniform(1, 3)
        elif scenario == "burst":
            background = rng.uniform(20, 25) if index % 3 == 1 else rng.uniform(1, 3)
        elif scenario == "overload":
            foreground, background = rng.uniform(23, 27), rng.uniform(20, 25)
        phases.append({"phase_index": index, "background_path": path,
                       "offered_mbps": round(foreground, 3),
                       "background_mbps": round(background, 3)})
    return phases


def worker():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("send", "receive"))
    parser.add_argument("--target", choices=("10.77.0.3", "10.77.0.4"))
    parser.add_argument("--mbps", type=float, default=1)
    args = parser.parse_args()
    if not 0 < args.mbps <= 30 or (args.kind == "send" and args.target is None):
        parser.error("Invalid fixed workload")
    running = True

    def stop(signum, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    started = time.monotonic()
    deadline = started + 40
    count, byteCount, highest = 0, 0, -1
    seen = set()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(0.1)
        if args.kind == "receive":
            sock.bind(("0.0.0.0", PORT))
            print(json.dumps({"ready": True}), flush=True)
        spacing = PACKET_BYTES * 8 / (args.mbps * 1e6)
        while running and time.monotonic() < deadline:
            if args.kind == "send":
                due = started + count * spacing
                wait = due - time.monotonic()
                if wait > 0:
                    time.sleep(min(wait, 0.01))
                    continue
                # Do not turn a scheduler stall into an unbounded catch-up burst.
                if time.monotonic() - due > 0.02:
                    started += time.monotonic() - due
                payload = struct.pack("!Q", count) + bytes(PACKET_BYTES - 8)
                sock.sendto(payload, (args.target, PORT))
            else:
                try:
                    payload, _ = sock.recvfrom(2048)
                except socket.timeout:
                    continue
                if len(payload) != PACKET_BYTES:
                    continue
                sequence = struct.unpack("!Q", payload[:8])[0]
                if sequence > 200000 or sequence in seen:
                    continue
                seen.add(sequence)
                highest = max(highest, sequence)
            count += 1
            byteCount += len(payload)
    print(json.dumps({"packets": count, "bytes": byteCount, "highest_sequence": highest}),
          flush=True)


if __name__ == "__main__":
    worker()
