"""Seeded workload inputs and bounded, real UDP probes (stdlib only)."""

import argparse
import json
import random
import signal
import socket
import struct
import time

SCENARIOS = ("low", "path0", "path1", "alternating", "burst", "overload")
SCHEDULE_VERSION = "seeded-stationary-profiles-v5"
# Explicit arrays are also exported in the hashed environment spec for independent replay.
MATCHED_PROFILES = {
    "low": {
        "offered_mbps": [5.8, 6.2],
        "background_mbps": [1.8, 2.2],
        "path_capacity_mbps": [[20], [20]],
        "capacity_draw_order": [0, 1],
    },
    "path0": {
        "offered_mbps": [5.8, 6.2],
        "background_mbps": [1.8, 2.2],
        "path_capacity_mbps": [[2], [20]],
        "capacity_draw_order": [0, 1],
    },
    "path1": {
        "offered_mbps": [5.8, 6.2],
        "background_mbps": [1.8, 2.2],
        "path_capacity_mbps": [[20], [2]],
        "capacity_draw_order": [0, 1],
    },
    "balanced": {
        "offered_mbps": [3, 5],
        "background_mbps": [1, 2],
        "path_capacity_mbps": [[20], [20]],
        "capacity_draw_order": [0, 1],
    },
    "moderate0": {
        "offered_mbps": [8, 10],
        "background_mbps": [1, 3],
        "path_capacity_mbps": [[6], [20]],
        "capacity_draw_order": [0, 1],
    },
    "moderate1": {
        "offered_mbps": [8, 10],
        "background_mbps": [1, 3],
        "path_capacity_mbps": [[20], [6]],
        "capacity_draw_order": [0, 1],
    },
    "severe0": {
        "offered_mbps": [7, 10],
        "background_mbps": [1, 3],
        "path_capacity_mbps": [[3, 4, 5], [12, 13, 14, 15, 16, 17, 18, 19, 20]],
        "capacity_draw_order": [0, 1],
    },
    "severe1": {
        "offered_mbps": [7, 10],
        "background_mbps": [1, 3],
        "path_capacity_mbps": [[12, 13, 14, 15, 16, 17, 18, 19, 20], [3, 4, 5]],
        "capacity_draw_order": [1, 0],
    },
    "overload": {
        "offered_mbps": [10, 12],
        "background_mbps": [2, 3],
        "path_capacity_mbps": [[6, 7, 8], [6, 7, 8]],
        "capacity_draw_order": [0, 1],
    },
}
MATCHED_SCENARIOS = tuple(MATCHED_PROFILES)
MATCHED_CAPACITIES = tuple(
    sorted({v for p in MATCHED_PROFILES.values() for c in p["path_capacity_mbps"] for v in c})
)
PORT = 19110
PACKET_BYTES = 1200


def schedule(seed, scenario, decisions, mode="sdn"):
    if type(seed) is not int or not 0 <= seed <= 2147483647:
        raise ValueError("seed must be an integer in 0..2147483647")
    scenarios = MATCHED_SCENARIOS if mode in ("matched", "ospf") else SCENARIOS
    if scenario not in scenarios or type(decisions) is not int or not 2 <= decisions <= 64:
        raise ValueError("Invalid scenario or episode length")
    rng = random.Random(seed)
    if mode in ("matched", "ospf"):
        profile = MATCHED_PROFILES[scenario]
        phase = {
            "background_path": 0,
            "offered_mbps": round(rng.uniform(*profile["offered_mbps"]), 3),
            "background_mbps": round(rng.uniform(*profile["background_mbps"]), 3),
        }
        capacities = [None, None]
        for path in profile["capacity_draw_order"]:
            choices = profile["path_capacity_mbps"][path]
            capacities[path] = choices[0] if len(choices) == 1 else rng.choice(choices)
        return [
            {"phase_index": index, **phase, "path_capacity_mbps": list(capacities)}
            for index in range(decisions + 1)
        ]
    if mode != "sdn":
        raise ValueError("Unknown workload mode")
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
        phases.append(
            {
                "phase_index": index,
                "background_path": path,
                "offered_mbps": round(foreground, 3),
                "background_mbps": round(background, 3),
            }
        )
    return phases


def worker():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("send", "receive"))
    parser.add_argument("--target", choices=("10.77.0.3", "10.77.0.4", "10.78.10.2", "10.78.11.2"))
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
    lifetimeStart = started
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
                if count == 0:
                    print(json.dumps({"ready": True}), flush=True)
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
    print(
        json.dumps(
            {
                "packets": count,
                "bytes": byteCount,
                "highest_sequence": highest,
                "duration_seconds": time.monotonic() - lifetimeStart,
                "started_monotonic_seconds": lifetimeStart,
                "finished_monotonic_seconds": time.monotonic(),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    worker()
