"""Ryu OpenFlow 1.3 discovery, deterministic unicast, and actual reply producer."""

import os
import time
from typing import ClassVar

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import (
    CONFIG_DISPATCHER,
    DEAD_DISPATCHER,
    MAIN_DISPATCHER,
    set_ev_cls,
)
from ryu.lib import hub
from ryu.lib.packet import ether_types, ethernet, ipv4, packet
from ryu.ofproto import ofproto_v1_3
from ryu.topology import event

from emulation.measurements import MultipartReplies, atomicJson, utcNow
from emulation.topology import HOSTS, SWITCHES, expectedLinks, nextPort, portCapacities


class CampusController(app_manager.RyuApp):
    OFP_VERSIONS: ClassVar[list] = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.datapaths = {}
        self.links = {}
        self.hosts = {}
        self.replies = MultipartReplies()
        self.statePath = os.environ.get("NANFO_CONTROLLER_STATE", "/run/nanfo/controller.json")
        self.worker = hub.spawn(self.monitor)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def features(self, ev):
        dp = ev.msg.datapath
        if f"{dp.id:016x}" not in {s["dpid"] for s in SWITCHES}:
            dp.close()
            return
        parser, ofp = dp.ofproto_parser, dp.ofproto
        dp.send_msg(
            parser.OFPFlowMod(
                datapath=dp,
                command=ofp.OFPFC_DELETE,
                cookie=1,
                cookie_mask=0xFFFFFFFFFFFFFFFF,
                table_id=1,
                out_port=ofp.OFPP_ANY,
                out_group=ofp.OFPG_ANY,
            )
        )
        actions = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        dp.send_msg(
            parser.OFPFlowMod(
                datapath=dp,
                priority=0,
                match=parser.OFPMatch(),
                instructions=[parser.OFPInstructionGotoTable(1)],
            )
        )
        dp.send_msg(
            parser.OFPFlowMod(
                datapath=dp,
                table_id=1,
                priority=0,
                match=parser.OFPMatch(),
                instructions=[parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)],
            )
        )

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def stateChange(self, ev):
        key = f"{ev.datapath.id:016x}"
        if key not in {s["dpid"] for s in SWITCHES}:
            return
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[key] = ev.datapath
        elif self.datapaths.get(key) is ev.datapath:
            del self.datapaths[key]
            self.replies.complete.pop(key, None)
            self.replies.pending.pop(key, None)
            self.links = {k: v for k, v in self.links.items() if key not in (k[0], k[2])}
            self.hosts = {k: v for k, v in self.hosts.items() if v[1]["dpid"] != key}
            self.clearForwarding()

    def clearForwarding(self):
        for dp in self.datapaths.values():
            dp.send_msg(
                dp.ofproto_parser.OFPFlowMod(
                    datapath=dp,
                    command=dp.ofproto.OFPFC_DELETE,
                    cookie=1,
                    cookie_mask=0xFFFFFFFFFFFFFFFF,
                    table_id=dp.ofproto.OFPTT_ALL,
                    out_port=dp.ofproto.OFPP_ANY,
                    out_group=dp.ofproto.OFPG_ANY,
                )
            )

    @set_ev_cls(event.EventLinkAdd)
    def linkAdd(self, ev):
        self.changeLink(ev.link, True)

    @set_ev_cls(event.EventLinkDelete)
    def linkDelete(self, ev):
        self.changeLink(ev.link, False)

    def changeLink(self, link, present):
        key = (f"{link.src.dpid:016x}", link.src.port_no, f"{link.dst.dpid:016x}", link.dst.port_no)
        if key not in expectedLinks():
            return
        if present:
            self.links[key] = dict(zip(("src_dpid", "src_port", "dst_dpid", "dst_port"), key))
        else:
            self.links.pop(key, None)
        self.clearForwarding()

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packetIn(self, ev):
        msg, dp = ev.msg, ev.msg.datapath
        frame = packet.Packet(msg.data)
        eth, ip = frame.get_protocol(ethernet.ethernet), frame.get_protocol(ipv4.ipv4)
        if not eth or eth.ethertype != ether_types.ETH_TYPE_IP or not ip:
            return  # Ryu's topology.switches consumes actual LLDP PacketIns separately.
        source = next((h for h in HOSTS if h["mac"] == eth.src and h["ipv4"] == ip.src), None)
        target = next((h for h in HOSTS if h["mac"] == eth.dst and h["ipv4"] == ip.dst), None)
        if source is None or target is None:
            return
        dpid, inPort = f"{dp.id:016x}", msg.match["in_port"]
        if (dpid, inPort) == (source["dpid"], source["port_no"]):
            # Configuration labels an identity only after its real ingress packet.
            self.hosts[source["name"]] = (time.monotonic(), dict(source))
        elif (dpid, inPort) not in {(k[0], k[1]) for k in self.links}:
            return
        outPort = (
            target["port_no"]
            if dpid == target["dpid"]
            else nextPort(dpid, target["dpid"], self.links.values())
        )
        if outPort is None or outPort == inPort:
            return
        parser, ofp = dp.ofproto_parser, dp.ofproto
        actions = [parser.OFPActionOutput(outPort)]
        dp.send_msg(
            parser.OFPFlowMod(
                datapath=dp,
                cookie=1,
                table_id=1,
                priority=100,
                idle_timeout=10,
                hard_timeout=30,
                match=parser.OFPMatch(
                    in_port=inPort,
                    eth_src=eth.src,
                    eth_dst=eth.dst,
                    eth_type=ether_types.ETH_TYPE_IP,
                    ipv4_src=ip.src,
                    ipv4_dst=ip.dst,
                ),
                instructions=[parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)],
            )
        )
        dp.send_msg(
            parser.OFPPacketOut(
                datapath=dp,
                buffer_id=ofp.OFP_NO_BUFFER,
                in_port=inPort,
                # Re-enter table 0 so a policy installed during PacketIn wins.
                actions=[parser.OFPActionOutput(ofp.OFPP_TABLE)],
                data=msg.data,
            )
        )

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def portStats(self, ev):
        msg = ev.msg
        dpid = f"{msg.datapath.id:016x}"
        fields = (
            "port_no",
            "rx_bytes",
            "tx_bytes",
            "rx_packets",
            "tx_packets",
            "rx_dropped",
            "tx_dropped",
        )
        rows = []
        capacities = portCapacities()
        for stat in msg.body:
            if f"{dpid}:{stat.port_no}" not in capacities:
                continue
            row = {field: getattr(stat, field) for field in fields}
            if any(v == 0xFFFFFFFFFFFFFFFF for v in row.values()):
                continue  # Unsupported counters are not measurements.
            row["duration_sec"] = stat.duration_sec + stat.duration_nsec / 1e9
            rows.append(row)
        self.replies.receive(
            dpid,
            "ports",
            msg.xid,
            rows,
            bool(msg.flags & msg.datapath.ofproto.OFPMPF_REPLY_MORE),
            utcNow(),
            time.monotonic(),
        )

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def flowStats(self, ev):
        msg = ev.msg
        fields = ("table_id", "priority", "cookie", "packet_count", "byte_count")
        rows = [
            {
                **{field: getattr(stat, field) for field in fields},
                "duration_sec": stat.duration_sec + stat.duration_nsec / 1e9,
            }
            for stat in msg.body
        ]
        self.replies.receive(
            f"{msg.datapath.id:016x}",
            "flows",
            msg.xid,
            rows,
            bool(msg.flags & msg.datapath.ofproto.OFPMPF_REPLY_MORE),
            utcNow(),
            time.monotonic(),
        )

    def monitor(self):
        names = {s["dpid"]: s["name"] for s in SWITCHES}
        while True:
            now = time.monotonic()
            for dpid, dp in list(self.datapaths.items()):
                pending = self.replies.pending.get(dpid)
                if pending and now - pending["started"] <= 5:
                    continue
                ports = dp.ofproto_parser.OFPPortStatsRequest(dp, 0, dp.ofproto.OFPP_ANY)
                flows = dp.ofproto_parser.OFPFlowStatsRequest(dp)
                dp.set_xid(ports)
                dp.set_xid(flows)
                self.replies.begin(dpid, ports.xid, flows.xid, now)
                dp.send_msg(ports)
                dp.send_msg(flows)
            samples = [
                {**s, "name": names[s["dpid"]]}
                for s in self.replies.samples(now)
                if s["dpid"] in self.datapaths
            ]
            atomicJson(
                self.statePath,
                {
                    "observed_at": utcNow(),
                    "switches": samples,
                    "links": list(self.links.values()),
                    "hosts": [h for seen, h in self.hosts.values() if now - seen <= 60],
                },
            )
            hub.sleep(1)
