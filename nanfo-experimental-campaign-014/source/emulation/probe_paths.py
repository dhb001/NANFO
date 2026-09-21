"""ADR018 selected ICMP probes and per-interface packet evidence (no planned routes).

The pure pcap decoder/reconstructor is also used by the read-only backend. Only
capturePaths touches namespaces; neither JSON claims nor ping output prove hops.
"""

import hashlib
import json
import os
import selectors
import signal
import socket
import struct
import subprocess
import sys
import time
import uuid
from contextlib import suppress
from datetime import datetime, timezone

from emulation.measurements import atomicJson, utcNow
from emulation.topology import HOSTS, LINKS, SWITCHES, TOPOLOGY_ID

MAX_PCAP_BYTES = 65536
MAX_PACKETS = 512
MAX_WINDOWS = 8
PREFIX = b"NANFO_PATH_V1:"


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def captureInterfaces():
    """Trusted port metadata; not a forwarding path."""
    switches = {s["name"]: s["dpid"] for s in SWITCHES}
    interfaces = {}
    for link in LINKS:
        for node, port in (link["a"], link["b"]):
            if node in switches or node in {"h1", "h3"}:
                interface = f"{node}-eth{port}"
                for direction in ("in", "out"):
                    key = f"{interface}-{direction}"
                    interfaces[key] = {
                        "interface": interface,
                        "direction": direction,
                        "dpid": switches.get(node),
                        "port_no": port,
                        "host": node if node not in switches else None,
                    }
    return interfaces


def probePayload(window_id, sequence):
    return PREFIX + uuid.UUID(window_id).bytes + struct.pack("!H", sequence)


def checksum(data):
    if len(data) % 2:
        data += b"\0"
    total = sum(struct.unpack(f"!{len(data) // 2}H", data))
    while total >> 16:
        total = (total & 65535) + (total >> 16)
    return (~total) & 65535


def sendProbes(window_id, identifier):
    """Runs inside h1's namespace. Replies/other traffic cannot match requests."""
    with socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP) as sender:
        sender.bind((HOSTS[0]["ipv4"], 0))
        for sequence in range(1, 4):
            packet = struct.pack("!BBHHH", 8, 0, 0, identifier, sequence)
            packet += probePayload(window_id, sequence)
            packet = packet[:2] + struct.pack("!H", checksum(packet)) + packet[4:]
            sender.sendto(packet, (HOSTS[2]["ipv4"], 0))
            time.sleep(0.15)


def decodePcap(data, capture_id, window_id, identifier):
    """Bounded classic Ethernet pcap, with full IP/ICMP integrity and payload checks."""
    if not 24 <= len(data) <= MAX_PCAP_BYTES:
        raise ValueError("pcap size invalid")
    formats = {
        b"\xd4\xc3\xb2\xa1": ("<", 1000000),
        b"\xa1\xb2\xc3\xd4": (">", 1000000),
        b"\x4d\x3c\xb2\xa1": ("<", 1000000000),
        b"\xa1\xb2\x3c\x4d": (">", 1000000000),
    }
    if data[:4] not in formats:
        raise ValueError("unsupported pcap format")
    endian, scale = formats[data[:4]]
    major, minor, _, _, snaplen, linktype = struct.unpack(endian + "HHIIII", data[4:24])
    if (major, minor) != (2, 4) or linktype != 1 or not 64 <= snaplen <= 65535:
        raise ValueError("unsupported pcap header")
    offset, index, packets = 24, 0, []
    while offset < len(data):
        if offset + 16 > len(data) or index >= MAX_PACKETS:
            raise ValueError("truncated or excessive pcap records")
        seconds, fraction, length, original = struct.unpack(
            endian + "IIII", data[offset : offset + 16]
        )
        offset += 16
        index += 1
        if (
            fraction >= scale
            or length > snaplen
            or length > original
            or offset + length > len(data)
        ):
            raise ValueError("invalid pcap record")
        frame = data[offset : offset + length]
        offset += length
        if len(frame) < 34 or frame[12:14] != b"\x08\x00":
            continue
        ip = frame[14:]
        ihl = (ip[0] & 15) * 4
        total = int.from_bytes(ip[2:4], "big")
        if ip[0] >> 4 != 4 or ihl < 20 or total < ihl + 8 or total > len(ip):
            raise ValueError("truncated IPv4 packet")
        if ip[9] != 1 or int.from_bytes(ip[6:8], "big") & 0x3FFF:
            continue
        icmp = ip[ihl:total]
        kind, code, _, packet_id, sequence = struct.unpack("!BBHHH", icmp[:8])
        if (kind, code, packet_id) != (8, 0, identifier) or sequence not in (1, 2, 3):
            continue
        if icmp[8:] != probePayload(window_id, sequence):
            continue
        if checksum(ip[:ihl]) or checksum(icmp):
            raise ValueError("packet checksum invalid")
        source, destination = socket.inet_ntoa(ip[12:16]), socket.inet_ntoa(ip[16:20])
        if (source, destination) != (HOSTS[0]["ipv4"], HOSTS[2]["ipv4"]):
            raise ValueError("probe endpoints differ")
        timestamp = datetime.fromtimestamp(seconds + fraction / scale, timezone.utc).isoformat()
        packets.append(
            {
                "capture_id": capture_id,
                "record_index": index,
                "timestamp": timestamp,
                "icmp_id": packet_id,
                "icmp_seq": sequence,
                "src_ip": source,
                "dst_ip": destination,
                "payload_sha256": hashlib.sha256(icmp[8:]).hexdigest(),
                "packet_sha256": hashlib.sha256(ip[:total]).hexdigest(),
            }
        )
    return packets


def observedPaths(packets, window_id, identifier):
    """Infer ordered switch hops only from matching receive/send interface sightings."""
    interfaces = captureInterfaces()
    peers = {}
    names = {s["name"]: s["dpid"] for s in SWITCHES}
    for link in LINKS:
        for (a, ap), (b, bp) in ((link["a"], link["b"]), (link["b"], link["a"])):
            if a in names and b in names:
                peers[(names[a], ap)] = (names[b], bp)
    paths = []
    for sequence in range(1, 4):
        selected, seen = [], set()
        for packet in packets:
            if packet["icmp_id"] != identifier or packet["icmp_seq"] != sequence:
                continue
            key = (packet["capture_id"], packet["timestamp"], packet["packet_sha256"])
            if key not in seen:
                selected.append(packet)
                seen.add(key)
        selected.sort(key=lambda p: (p["timestamp"], p["capture_id"], p["record_index"]))
        groups, sources, destinations = {}, [], []
        unexpected_host_direction = False
        for packet in selected:
            meta = interfaces[packet["capture_id"]]
            if meta["dpid"]:
                groups.setdefault(meta["dpid"], {"in": [], "out": []})[meta["direction"]].append(
                    packet
                )
            elif meta["host"] == "h1" and meta["direction"] == "out":
                sources.append(packet)
            elif meta["host"] == "h3" and meta["direction"] == "in":
                destinations.append(packet)
            else:
                unexpected_host_direction = True
        ambiguous = (
            len(sources) > 1
            or len(destinations) > 1
            or len({p["packet_sha256"] for p in selected}) > 1
            or unexpected_host_direction
        )
        hops = []
        for dpid, directions in groups.items():
            incoming, outgoing = directions["in"], directions["out"]
            ambiguous |= len(incoming) > 1 or len(outgoing) > 1
            # Multiple candidate ports must never be flattened into a successful route.
            ingress = incoming[0] if len(incoming) == 1 else None
            egress = outgoing[0] if len(outgoing) == 1 else None
            hops.append(
                {
                    "dpid": dpid,
                    "ingress_port": interfaces[ingress["capture_id"]]["port_no"]
                    if ingress
                    else None,
                    "egress_port": interfaces[egress["capture_id"]]["port_no"] if egress else None,
                    "received_at": ingress["timestamp"] if ingress else None,
                    "sent_at": egress["timestamp"] if egress else None,
                }
            )
        hops.sort(key=lambda h: (h["received_at"] or "~", h["dpid"]))
        complete = bool(sources and destinations and hops) and not ambiguous
        for hop in hops:
            complete &= bool(
                hop["received_at"] and hop["sent_at"] and hop["received_at"] <= hop["sent_at"]
            )
        if complete:
            complete &= (
                (hops[0]["dpid"], hops[0]["ingress_port"])
                == (HOSTS[0]["dpid"], HOSTS[0]["port_no"])
                and (hops[-1]["dpid"], hops[-1]["egress_port"])
                == (HOSTS[2]["dpid"], HOSTS[2]["port_no"])
                and sources[0]["timestamp"] <= hops[0]["received_at"]
                and hops[-1]["sent_at"] <= destinations[0]["timestamp"]
            )
            for before, after in zip(hops, hops[1:]):
                linked = peers.get((before["dpid"], before["egress_port"]))
                complete &= (
                    linked == (after["dpid"], after["ingress_port"])
                    and before["sent_at"] <= after["received_at"]
                )
                ambiguous |= before["received_at"] == after["received_at"]
        paths.append(
            {
                "packet_id": f"{window_id}:{identifier}:{sequence}",
                "icmp_id": identifier,
                "icmp_seq": sequence,
                "src_host": "h1",
                "dst_host": "h3",
                "src_ip": HOSTS[0]["ipv4"],
                "dst_ip": HOSTS[2]["ipv4"],
                "source_timestamp": sources[0]["timestamp"] if len(sources) == 1 else None,
                "destination_timestamp": destinations[0]["timestamp"]
                if len(destinations) == 1
                else None,
                "status": "ambiguous" if ambiguous else "measured" if complete else "partial",
                "observed_hops": hops,
                "captured_packet_count": len(selected),
            }
        )
    return paths


class CaptureInterrupted(RuntimeError):
    """Control service changed the lab; this window cannot claim stable completion."""


def capturePaths(lab, service_controls=None):
    """Fixed local diagnostic: h1 -> h3, three requests, <=8 retained windows."""
    mailbox = getattr(lab, "mailbox", None)
    generation = mailbox.control_generation if mailbox is not None else None

    def checkpoint():
        nonlocal generation
        if getattr(lab, "stopping", False):
            raise CaptureInterrupted("Lab stopping")
        if service_controls is not None:
            changed = service_controls()
        elif mailbox is not None:
            # Do not dispatch new actions as a side effect of a diagnostic.
            mailbox.poll(cancel_only=True)
            changed = generation != mailbox.control_generation
            generation = mailbox.control_generation
        else:
            changed = False
        if changed or getattr(lab, "stopping", False):
            raise CaptureInterrupted("Controls changed during capture")

    checkpoint()  # A pending STOP/cancel must precede any capture process or output.

    # A hard retention cap avoids deleting artifacts another operator may be reviewing.
    if len(list(lab.output.glob("probe-capture-*"))) >= MAX_WINDOWS:
        raise RuntimeError("Probe capture retention full; archive owned windows before capturing")
    window_id = str(uuid.uuid4())
    identifier = 1 + uuid.uuid4().int % 65535
    directory = lab.output / ("probe-capture-" + window_id)
    directory.mkdir(mode=0o755)
    processes, captures, packets = [], [], []
    sender = None
    started = utcNow()
    try:
        with selectors.DefaultSelector() as ready:
            for capture_id, meta in captureInterfaces().items():
                checkpoint()
                path = directory / (capture_id + ".pcap")
                args = [
                    "tcpdump",
                    "-n",
                    "-U",
                    "--immediate-mode",
                    "-s",
                    "256",
                    "-c",
                    "64",
                    "-Q",
                    meta["direction"],
                    "-i",
                    meta["interface"],
                    "-w",
                    str(path),
                    f"icmp and src host {HOSTS[0]['ipv4']} and dst host {HOSTS[2]['ipv4']} "
                    f"and icmp[0] = 8 and icmp[4:2] = {identifier}",
                ]
                node = lab.net[meta["host"]] if meta["host"] else None
                process = (node.popen if node else subprocess.Popen)(
                    args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
                )
                processes.append(process)
                lab.processes.append(process)
                ready.register(process.stderr, selectors.EVENT_READ, process)
                captures.append(
                    {
                        "capture_id": capture_id,
                        **meta,
                        "file": f"probe-capture-{window_id}/{capture_id}.pcap",
                    }
                )
            deadline = time.monotonic() + 8
            buffers = {}
            while ready.get_map():
                checkpoint()
                if time.monotonic() >= deadline:
                    raise RuntimeError("tcpdump readiness deadline exceeded")
                for key, _ in ready.select(0.1):
                    chunk = os.read(key.fileobj.fileno(), 4096)
                    buffers[key.fd] = buffers.get(key.fd, b"") + chunk
                    if not chunk or key.data.poll() is not None:
                        raise RuntimeError("tcpdump failed readiness")
                    if b"listening on" in buffers[key.fd]:
                        ready.unregister(key.fileobj)
        checkpoint()
        sender = lab.net["h1"].popen(
            [sys.executable, "-m", "emulation.probe_paths", window_id, str(identifier)]
        )
        lab.processes.append(sender)
        deadline = time.monotonic() + 3
        while sender.poll() is None:
            checkpoint()
            if time.monotonic() >= deadline:
                raise RuntimeError("probe generator timeout")
            time.sleep(0.05)
        if sender.returncode:
            raise RuntimeError("probe generator failed")
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            checkpoint()
            time.sleep(0.05)
        for process in processes:
            checkpoint()
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
        deadline = time.monotonic() + 3
        for process, capture in zip(processes, captures):
            checkpoint()
            while True:
                checkpoint()
                try:
                    _, error = process.communicate(timeout=0.05)
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("tcpdump shutdown timeout") from None
            # Drops or early exits make the window unavailable, never complete.
            if process.returncode != 0 or b"0 packets dropped by kernel" not in error:
                raise RuntimeError("tcpdump incomplete or dropped packets")
            data = (lab.output / capture["file"]).read_bytes()
            capture.update(sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))
            packets.extend(decodePcap(data, capture["capture_id"], window_id, identifier))
        ended = utcNow()
        if len(packets) > MAX_PACKETS:
            raise RuntimeError("probe packet limit exceeded")
        artifact = {
            "version": 1,
            "topology_id": TOPOLOGY_ID,
            "run_id": lab.runId,
            "window_id": window_id,
            "window_start": started,
            "window_end": ended,
            "icmp_id": identifier,
            "scope": "selected_probe_only",
            "captures": captures,
            "packets": packets,
            "paths": observedPaths(packets, window_id, identifier),
        }
        artifact["evidence_sha256"] = digest(artifact)
        checkpoint()
        atomicJson(directory / "artifact.json", artifact)
        atomicJson(lab.output / "probe-paths.json", artifact)
        lab.snapshot()
        return {
            "passed": all(p["status"] == "measured" for p in artifact["paths"]),
            "run_id": lab.runId,
            "window_id": window_id,
            "artifact": "probe-paths.json",
            "captured_packet_count": len(packets),
            "paths": artifact["paths"],
            "evidence_sha256": artifact["evidence_sha256"],
        }
    finally:
        # Stop all owned children together, not forty sequential three-second waits.
        owned = [*processes, *([sender] if sender is not None else [])]
        for process in owned:
            if process.poll() is None:
                process.kill()
        deadline = time.monotonic() + 3
        for process in owned:
            while process.poll() is None and time.monotonic() < deadline:
                with suppress(Exception):  # Cleanup must reap every child even if control fails.
                    checkpoint()
                time.sleep(0.05)
            if process.poll() is not None:
                for stream in (process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
                if process in lab.processes:
                    lab.processes.remove(process)


if __name__ == "__main__":
    sendProbes(str(uuid.UUID(sys.argv[1])), int(sys.argv[2]))
