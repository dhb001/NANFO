"""Trusted campus configuration, deliberately independent of Mininet and Ryu."""

from collections import deque
from copy import deepcopy

TOPOLOGY_ID = "campus-small-v1"
SWITCHES = (
    {"name": "core", "dpid": "0000000000000001", "role": "core"},
    {"name": "dist1", "dpid": "0000000000000002", "role": "distribution"},
    {"name": "dist2", "dpid": "0000000000000003", "role": "distribution"},
    {"name": "access1", "dpid": "0000000000000004", "role": "access"},
    {"name": "access2", "dpid": "0000000000000005", "role": "access"},
)
HOSTS = tuple(
    {
        "name": f"h{i}",
        "mac": f"02:00:00:00:00:{i:02x}",
        "ipv4": f"10.77.0.{i}",
        "dpid": f"{4 if i <= 2 else 5:016x}",
        "port_no": 3 if i % 2 else 4,
    }
    for i in range(1, 5)
)
# Endpoint tuples are (node name, explicitly assigned OpenFlow/interface port).
LINKS = (
    {
        "a": ("core", 1),
        "b": ("dist1", 1),
        "capacity_mbps": 100,
        "delay_ms": 2,
        "max_queue_size": 100,
    },
    {
        "a": ("core", 2),
        "b": ("dist2", 1),
        "capacity_mbps": 100,
        "delay_ms": 2,
        "max_queue_size": 100,
    },
    {
        "a": ("dist1", 2),
        "b": ("dist2", 2),
        "capacity_mbps": 50,
        "delay_ms": 3,
        "max_queue_size": 100,
    },
    {
        "a": ("dist1", 3),
        "b": ("access1", 1),
        "capacity_mbps": 20,
        "delay_ms": 5,
        "max_queue_size": 100,
    },
    {
        "a": ("dist2", 3),
        "b": ("access1", 2),
        "capacity_mbps": 20,
        "delay_ms": 5,
        "max_queue_size": 100,
    },
    {
        "a": ("dist1", 4),
        "b": ("access2", 1),
        "capacity_mbps": 20,
        "delay_ms": 5,
        "max_queue_size": 100,
    },
    {
        "a": ("dist2", 4),
        "b": ("access2", 2),
        "capacity_mbps": 20,
        "delay_ms": 5,
        "max_queue_size": 100,
    },
    *(
        {
            "a": ("access1" if i <= 2 else "access2", 3 if i % 2 else 4),
            "b": (f"h{i}", 0),
            "capacity_mbps": 100,
            "delay_ms": 1,
            "max_queue_size": 100,
        }
        for i in range(1, 5)
    ),
)


def manifest():
    """Return a detached JSON-serializable manifest for an operator-side binder."""
    return deepcopy(
        {
            "topology_id": TOPOLOGY_ID,
            "switches": list(SWITCHES),
            "hosts": list(HOSTS),
            "links": list(LINKS),
            "port_capacities_mbps": portCapacities(),
        }
    )


def portCapacities():
    names = {s["name"]: s["dpid"] for s in SWITCHES}
    return {
        f"{names[node]}:{port}": link["capacity_mbps"]
        for link in LINKS
        for node, port in (link["a"], link["b"])
        if node in names
    }


def expectedLinks():
    names = {s["name"]: s["dpid"] for s in SWITCHES}
    return {
        (names[a], ap, names[b], bp)
        for link in LINKS
        for (a, ap), (b, bp) in ((link["a"], link["b"]), (link["b"], link["a"]))
        if a in names and b in names
    }


def nextPort(source, destination, observedLinks):
    """Sorted shortest path over bidirectionally observed links; never flood."""
    links = {
        (link["src_dpid"], link["src_port"], link["dst_dpid"], link["dst_port"])
        for link in observedLinks
    }
    graph = {}
    for src, port, dst, peerPort in sorted(links & expectedLinks()):
        if (dst, peerPort, src, port) in links:
            graph.setdefault(src, []).append((dst, port))
    pending = deque([(source, None)])
    visited = {source}
    while pending:
        node, first = pending.popleft()
        if node == destination:
            return first
        for peer, port in graph.get(node, []):
            if peer not in visited:
                visited.add(peer)
                pending.append((peer, port if first is None else first))
    return None


if __name__ == "__main__":
    import json

    print(json.dumps(manifest(), indent=2))
