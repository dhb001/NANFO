"""Pure native FRR topology/route binding, including immutable link-local demands."""

from emulation.autonomous_contract import PATHS
from emulation.ospf import OSPFNetwork, linkPlan


def execution_map(background_paths):
    """Require actually read-back background paths; never assume OSPF placement.

    Link-local ARP/OSPF classes become per-directed-link demands. They do not
    pretend to be host-routed traffic, nor disappear when foreground moves.
    """
    graph = linkPlan()
    host_addresses = OSPFNetwork().hostAddresses
    egresses = {}
    pairs = {}
    for link in graph:
        for endpoint in link["endpoints"]:
            node, peer = endpoint["node"], endpoint["peer"]
            key = node + "_" + peer
            pairs[node, peer] = key
            egresses[key] = {"node": node, "interface": endpoint["interface"],
                            "queue_handle": "10:", "source": node, "destination": peer}
    if set(background_paths) != {"h2_h4", "h4_h2"}:
        raise ValueError("native_background_readback_required")

    def chain(nodes, source, destination):
        if (not isinstance(nodes, list) or not nodes or nodes[0] != source or nodes[-1] != destination
                or len(set(nodes)) != len(nodes)):
            raise ValueError("native_route_not_simple_connected_path")
        try:
            return [pairs[a, b] for a, b in zip(nodes, nodes[1:])]
        except KeyError as exc:
            raise ValueError("native_route_not_in_exact_topology") from exc

    actions = {}
    for action, path in enumerate(PATHS):
        paths = {"h1_h3": ["h1", *path, "h3"], "h3_h1": ["h3", *reversed(path), "h1"],
                 **background_paths}
        mapping = {key: chain(nodes, *key.split("_")) for key, nodes in paths.items()}
        for key in egresses:
            mapping[key + "_arp"] = [key]
            mapping[key + "_ospf"] = [key]
        actions[str(action)] = mapping
    return {"egresses": egresses, "host_addresses": host_addresses, "actions": actions,
            "required_transitions": [["0", "0"], ["0", "1"], ["1", "1"], ["1", "0"]],
            "transition_egresses": {f"{old}->{new}": {
                demand: sorted(set(actions[old][demand]) | set(actions[new][demand]))
                for demand in actions[old]} for old in actions for new in actions}}


def assert_design_mapping(spec, mapping):
    """The bound must cover hosts AND every router interface, even unused paths."""
    actual = {e["egress_id"]: {"node": e["node"], "interface": e["interface"],
              "queue_handle": "10:", "source": e["node"], "destination": e["peer"]}
              for e in spec["egresses"]}
    if actual != mapping["egresses"] or spec["host_addresses"] != mapping["host_addresses"]:
        raise ValueError("native_design_not_exact_frr_graph")


def mutation_manifest(action):
    """Exact existing-driver commands and partial-state prefixes, without I/O.

    These are a review manifest, not an executor. The receiver remains the only
    dispatch/recovery boundary. Prefixes identify all non-atomic rule states that
    the acquisition controller must trace, including recovery after each prefix.
    """
    from emulation.autonomous_frr import LinuxFRRDriver

    if type(action) is not int or action not in (0, 1):
        raise ValueError("native_action_outside_frozen_map")
    driver = LinuxFRRDriver(OSPFNetwork(), resource_id="offline-design", run_id="offline-design",
        binding_sha256="0" * 64, ownership_check=lambda *_: False, dispatch_guard=lambda *_: False)
    resources = driver.resources(action)
    operations = [{"node": row["node"], "argv": driver.command(row, kind, "add")}
                  for row in resources for kind in ("routes", "rules")]
    recovery = [{"node": row["node"], "argv": driver.command(row, kind, "del")}
                for row in reversed(resources) for kind in ("rules", "routes")]
    return {"action": action, "resources": resources, "apply": operations, "recover": recovery,
            "partial_state_prefixes": [operations[:i] for i in range(len(operations) + 1)],
            "authorization": False}
