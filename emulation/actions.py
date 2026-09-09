"""Container-local bounded OVS/HTB driver. No caller-supplied CLI or interface."""

import json
import re
import subprocess

from emulation.topology import HOSTS, LINKS, SWITCHES, expectedLinks

NAMES = {s["dpid"]: s["name"] for s in SWITCHES}
HOST_MAP = {h["name"]: h for h in HOSTS}
PORTS = {
    (a, b): (ap, bp)
    for link in LINKS
    for (a, ap), (b, bp) in ((link["a"], link["b"]), (link["b"], link["a"]))
}
COOKIE = "0x4e414e4600000001"
RESOURCE = 19001


def cli(args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=4).stdout


def tcRead(kind, interface):
    text = cli(["tc", "-j", kind, "show", "dev", interface]).strip()
    if not text or text.startswith("["):
        return json.loads(text or "[]")
    # Bullseye iproute2 supports JSON qdiscs/filters but still prints HTB classes.
    if kind != "class":
        raise ValueError("Unsupported tc readback")
    rows = []
    for line in text.splitlines():
        match = re.fullmatch(
            r"class htb (\S+) (root|parent \S+) leaf (\S+) prio (\d+) rate ([\d.]+)([KMG]?)bit ceil ([\d.]+)([KMG]?)bit burst (\S+) cburst (\S+)\s*",
            line,
        )
        if not match:
            # New classes have no leaf during partial-action reconciliation.
            match = re.fullmatch(
                r"class htb (\S+) (root|parent \S+) (?:leaf (\S+) )?prio (\d+) rate ([\d.]+)([KMG]?)bit ceil ([\d.]+)([KMG]?)bit burst (\S+) cburst (\S+)\s*",
                line,
            )
        if not match:
            raise ValueError("Unsupported HTB class readback: " + line[:160])
        handle, parent, leaf, priority, rate, unit, ceil, ceilUnit, burst, cburst = match.groups()
        scale = {"": 1, "K": 1000, "M": 1000000, "G": 1000000000}
        rows.append(
            {
                "kind": "htb",
                "handle": handle,
                "parent": parent,
                "options": {
                    "rate": float(rate) * scale[unit] / 8,
                    "ceil": float(ceil) * scale[ceilUnit] / 8,
                    "leaf": leaf,
                    "priority": priority,
                    "burst": burst,
                    "cburst": cburst,
                },
            }
        )
    return rows


class Actions:
    def __init__(self, lab):
        self.lab = lab

    def of(self, operation, switch, value=None):
        args = ["ovs-ofctl", "-O", "OpenFlow13", "--timeout=3", operation, switch]
        if value is not None:
            args.append(value)
        return cli(args)

    def capture(self):
        switches = {}
        for switch in NAMES.values():
            switches[switch] = {
                "flows": self.of("dump-flows", switch, "table=0"),
                "groups": self.of("dump-groups", switch),
                "meters": self.of("dump-meters", switch),
            }
        queues = {}
        for host in HOSTS:
            interface = f"{NAMES[host['dpid']]}-eth{host['port_no']}"
            queues[interface] = {
                kind: tcRead(kind, interface) for kind in ("qdisc", "class", "filter")
            }
        return {"switches": switches, "queues": queues}

    def prepare(self, plan):
        state = self.lab.controllerState()
        if not self.lab.ready(state):
            raise ValueError("Fresh observed topology and host attachments required")
        observed = {
            (link["src_dpid"], link["src_port"], link["dst_dpid"], link["dst_port"])
            for link in state["links"]
        }
        if observed != expectedLinks():
            raise ValueError("Observed link set mismatch")
        before = self.capture()
        for row in before["switches"].values():
            if (
                COOKIE in row["flows"]
                or f"group_id={RESOURCE}" in row["groups"]
                or f"meter={RESOURCE}" in row["meters"]
            ):
                raise ValueError("Unjournaled owned OpenFlow state")
            dataFlows = [line for line in row["flows"].splitlines() if "dl_type=0x88cc" not in line]
            if any(int(p) > 0 for p in re.findall(r"priority=(\d+)", "\n".join(dataFlows))):
                raise ValueError("Unowned table-0 policy conflict")
        op = plan["operation"]
        source, target = (HOST_MAP[plan[k]] for k in ("source_host", "destination_host"))
        flows, groups, meters, shapes = [], [], [], []
        for src, dst, reverse in ((source, target, False), (target, source, True)):
            match = f"ip,dl_src={src['mac']},dl_dst={dst['mac']},nw_src={src['ipv4']},nw_dst={dst['ipv4']}"
            if plan["dscp"] is not None:
                match += f",ip_dscp={plan['dscp']}"
            switch = NAMES[src["dpid"]]
            if op in ("reroute", "multipath"):
                paths = [list(reversed(p)) if reverse else p for p in plan["paths"]]
                routes = {}
                for index, path in enumerate(paths):
                    for i, node in enumerate(path):
                        ingress = src["port_no"] if i == 0 else PORTS[node, path[i - 1]][0]
                        egress = (
                            dst["port_no"] if i == len(path) - 1 else PORTS[node, path[i + 1]][0]
                        )
                        routes.setdefault((node, ingress), {})[egress] = plan["weights"][index]
                for (node, ingress), outputs in routes.items():
                    action = f"output:{next(iter(outputs))}"
                    if len(outputs) > 1:
                        features = self.of("dump-group-features", node)
                        if "select" not in features.lower():
                            raise ValueError("SELECT groups unsupported")
                        group = f"group_id={RESOURCE},type=select," + ",".join(
                            f"bucket=weight:{weight},actions=output:{port}"
                            for port, weight in outputs.items()
                        )
                        groups.append([node, group])
                        action = f"group:{RESOURCE}"
                    flows.append(
                        [
                            node,
                            f"cookie={COOKIE},table=0,priority=30000,in_port={ingress},{match},actions={action}",
                        ]
                    )
            elif op == "police":
                features = self.of("meter-features", switch)
                if not all(word in features.lower() for word in ("kbps", "drop")):
                    raise ValueError("OF1.3 kbps/drop meters unsupported")
                meter = f"meter={RESOURCE},kbps,burst,bands=type=drop,rate={int(plan['rate_mbps'] * 1000)},burst_size={int(plan['rate_mbps'] * 100)}"
                if [switch, meter] not in meters:
                    meters.append([switch, meter])
                flows.append(
                    [
                        switch,
                        f"cookie={COOKIE},table=0,priority=30000,in_port={src['port_no']},{match},actions=meter:{RESOURCE},goto_table:1",
                    ]
                )
            elif op == "shape":
                interface = f"{NAMES[dst['dpid']]}-eth{dst['port_no']}"
                queue = before["queues"][interface]
                roots = [r for r in queue["qdisc"] if r["kind"] == "htb" and r.get("root")]
                leaves = [r for r in queue["qdisc"] if r["kind"] == "netem"]
                if (
                    len(roots) != 1
                    or len(leaves) != 1
                    or len(queue["class"]) != 1
                    or queue["filter"]
                ):
                    raise ValueError("Unsupported existing HTB/netem hierarchy")
                root, leaf = roots[0], leaves[0]
                if root["handle"] != "5:" or leaf.get("parent") != "5:1":
                    raise ValueError("Unsupported HTB handles")
                shapes.append(
                    {
                        "interface": interface,
                        "src": src["ipv4"],
                        "dst": dst["ipv4"],
                        "rate": plan["rate_mbps"],
                        "dscp": plan["dscp"],
                    }
                )
        return {
            "before": before,
            "flows": flows,
            "groups": groups,
            "meters": meters,
            "shapes": shapes,
        }

    def reconcile(self, prepared=None):
        if prepared is not None:
            return self.verify(prepared)
        actual = self.capture()
        for row in actual["switches"].values():
            if (
                COOKIE in row["flows"]
                or re.search(rf"group_id={RESOURCE}\b", row["groups"])
                or re.search(rf"meter={RESOURCE}\b", row["meters"])
            ):
                raise RuntimeError("Unjournaled owned OpenFlow state")
        for queue in actual["queues"].values():
            if any(
                row.get("handle") in ("5:100", "20:")
                for kind in ("qdisc", "class")
                for row in queue[kind]
            ) or any(row.get("pref") == 30000 for row in queue["filter"]):
                raise RuntimeError("Unjournaled owned queue state")
        return actual

    @staticmethod
    def verifySelector(rows, shape):
        filters = [row for row in rows if row.get("options", {}).get("handle") is not None]
        if len(filters) != 1:
            raise RuntimeError("Expected one concrete HTB selector")
        row = filters[0]
        options = row["options"]
        keys = options.get("keys", {})
        expected = {"eth_type": "ipv4", "src_ip": shape["src"], "dst_ip": shape["dst"]}
        if shape["dscp"] is not None:
            expected["ip_tos"] = shape["dscp"] << 2
            expected["ip_tos_mask"] = 252
        if (
            row.get("kind") != "flower"
            or row.get("protocol") != "ip"
            or row.get("pref") != 30000
            or options.get("classid") != "5:100"
            or keys != expected
        ):
            raise RuntimeError(f"HTB selector readback mismatch: {keys}")

    def apply(self, prepared, checkpoint):
        # ovs-ofctl modification commands wait for an OF barrier on the same
        # connection and return nonzero on OF errors. Readback is independent.
        for kind, operation in (
            ("groups", "add-group"),
            ("meters", "add-meter"),
            ("flows", "add-flow"),
        ):
            for switch, value in prepared[kind]:
                checkpoint()
                self.of(operation, switch, value)
        for shape in prepared["shapes"]:
            interface = shape["interface"]
            commands = [
                [
                    "class",
                    "add",
                    "dev",
                    interface,
                    "parent",
                    "5:",
                    "classid",
                    "5:100",
                    "htb",
                    "rate",
                    f"{shape['rate']}mbit",
                    "ceil",
                    f"{shape['rate']}mbit",
                ],
                [
                    "qdisc",
                    "add",
                    "dev",
                    interface,
                    "parent",
                    "5:100",
                    "handle",
                    "20:",
                    "netem",
                    "delay",
                    "1ms",
                    "limit",
                    "100",
                ],
                [
                    "filter",
                    "add",
                    "dev",
                    interface,
                    "protocol",
                    "ip",
                    "parent",
                    "5:",
                    "pref",
                    "30000",
                    "flower",
                    "src_ip",
                    shape["src"],
                    "dst_ip",
                    shape["dst"],
                    *(
                        ["ip_tos", f"{shape['dscp'] << 2}/0xfc"]
                        if shape["dscp"] is not None
                        else []
                    ),
                    "classid",
                    "5:100",
                ],
            ]
            for command in commands:
                checkpoint()
                cli(["tc", *command])

    @staticmethod
    def queueConfig(queue):
        return {
            kind: [
                {
                    k: row[k]
                    for k in ("kind", "handle", "parent", "root", "options", "pref", "protocol")
                    if k in row
                }
                for row in rows
            ]
            for kind, rows in queue.items()
        }

    def verify(self, prepared, absent=False):
        actual = self.capture()
        for switch, flow in prepared["flows"]:
            lines = [
                line for line in actual["switches"][switch]["flows"].splitlines() if COOKIE in line
            ]
            if absent:
                if lines:
                    raise RuntimeError("Owned flows remain")
            else:
                expected = flow.split(",actions=")
                tokens = re.sub(
                    r"ip_dscp=(\d+)", lambda m: f"nw_tos={int(m.group(1)) << 2}", expected[0]
                ).split(",")
                if not any(
                    all(token in line.replace(" ", ",").split(",") for token in tokens)
                    and line.split(" actions=")[-1] == expected[1]
                    for line in lines
                ):
                    raise RuntimeError("Flow readback mismatch: " + str(lines)[:500])
        for kind, key in (("groups", "group_id"), ("meters", "meter")):
            for switch, value in prepared[kind]:
                text = actual["switches"][switch][kind]
                if absent:
                    if f"{key}={RESOURCE}" in text:
                        raise RuntimeError("Owned resource remains")
                else:
                    if kind == "groups":
                        buckets = re.findall(r"bucket=(?:weight:(\d+),)?actions=output:(\d+)", text)
                        expected = re.findall(r"bucket=weight:(\d+),actions=output:(\d+)", value)
                        matched = [(weight or "1", port) for weight, port in buckets] == expected
                        matched = matched and f"group_id={RESOURCE},type=select" in text
                    else:
                        matched = all(
                            token in text for token in value.replace("bands=", "").split(",")
                        )
                    if not matched:
                        raise RuntimeError(f"{kind} readback mismatch: {text[:500]}")
        for shape in prepared["shapes"]:
            interface = shape["interface"]
            queue = actual["queues"][interface]
            before = prepared["before"]["queues"][interface]
            if absent:
                if self.queueConfig(queue) != self.queueConfig(before):
                    raise RuntimeError("HTB/netem restoration mismatch")
            else:
                classes = [r for r in queue["class"] if r.get("handle") == "5:100"]
                if (
                    len(classes) != 1
                    or abs(classes[0]["options"]["rate"] * 8 / 1e6 - shape["rate"]) > 0.01
                ):
                    raise RuntimeError("HTB rate readback mismatch")
                self.verifySelector(queue["filter"], shape)
                preserved = {
                    kind: [r for r in rows if r.get("handle") not in ("5:100", "20:")]
                    for kind, rows in queue.items()
                    if kind != "filter"
                }
                if self.queueConfig(preserved) != self.queueConfig(
                    {k: v for k, v in before.items() if k != "filter"}
                ):
                    raise RuntimeError("Existing netem/HTB configuration changed")
        return actual

    def rollback(self, prepared, checkpoint=lambda: None):
        for switch in {row[0] for row in prepared["flows"]}:
            checkpoint()
            self.of("del-flows", switch, f"cookie={COOKIE}/-1,table=0")
        for kind, operation, key in (
            ("groups", "del-groups", "group_id"),
            ("meters", "del-meters", "meter"),
        ):
            for switch, _ in prepared[kind]:
                checkpoint()
                self.of(operation, switch, f"{key}={RESOURCE}")
        for shape in prepared["shapes"]:
            interface = shape["interface"]
            current = {kind: tcRead(kind, interface) for kind in ("filter", "qdisc", "class")}
            if any(r.get("pref") == 30000 for r in current["filter"]):
                checkpoint()
                cli(
                    [
                        "tc",
                        "filter",
                        "del",
                        "dev",
                        interface,
                        "parent",
                        "5:",
                        "protocol",
                        "ip",
                        "pref",
                        "30000",
                    ]
                )
            if any(r.get("handle") == "20:" for r in current["qdisc"]):
                checkpoint()
                cli(["tc", "qdisc", "del", "dev", interface, "parent", "5:100", "handle", "20:"])
            if any(r.get("handle") == "5:100" for r in current["class"]):
                checkpoint()
                cli(["tc", "class", "del", "dev", interface, "classid", "5:100"])
        return self.verify(prepared, absent=True)

    def probe(self, plan):
        src, dst = (HOST_MAP[plan[k]] for k in ("source_host", "destination_host"))
        process = self.lab.net[src["name"]].popen(
            [
                "ping",
                "-n",
                "-c",
                "3",
                "-i",
                ".1",
                "-W",
                "1",
                "-Q",
                str((plan["dscp"] or 0) << 2),
                dst["ipv4"],
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            text = process.communicate(timeout=5)[0].decode()
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise
        if process.returncode or not re.search(r"3 (?:packets )?received", text):
            raise RuntimeError("Bidirectional traffic probe failed")
        return {
            "sent": 3,
            "received": 3,
            "source_host": src["name"],
            "destination_host": dst["name"],
        }
