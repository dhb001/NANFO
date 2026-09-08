"""Real Ryu packet/parser tests run in the pinned image, never require a network."""

import importlib.util
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from emulation.topology import HOSTS


@unittest.skipUnless(importlib.util.find_spec("ryu"), "Ryu is installed only in the lab image")
class ControllerTests(unittest.TestCase):
    def setUp(self):
        from emulation.controller import CampusController
        from ryu.ofproto import ofproto_v1_3, ofproto_v1_3_parser

        self.app = CampusController.__new__(CampusController)
        self.app.hosts = {}
        self.app.links = {}
        self.dp = SimpleNamespace(
            id=4, ofproto=ofproto_v1_3, ofproto_parser=ofproto_v1_3_parser, send_msg=Mock()
        )

    def event(self, port, ethertype=0x0800, source=None):
        from ryu.lib.packet import ethernet, ipv4, packet

        source = source or HOSTS[0]
        frame = packet.Packet()
        frame.add_protocol(
            ethernet.ethernet(src=source["mac"], dst=HOSTS[1]["mac"], ethertype=ethertype)
        )
        frame.add_protocol(ipv4.ipv4(src=source["ipv4"], dst=HOSTS[1]["ipv4"]))
        frame.serialize()
        return SimpleNamespace(
            msg=SimpleNamespace(datapath=self.dp, data=frame.data, match={"in_port": port})
        )

    def testHostRequiresActualExpectedIngressPacket(self):
        self.assertEqual(self.app.hosts, {})
        self.app.packetIn(self.event(1))
        self.assertEqual(self.app.hosts, {})
        self.dp.send_msg.assert_not_called()
        self.app.packetIn(self.event(3))
        self.assertEqual(self.app.hosts["h1"][1], HOSTS[0])
        self.assertEqual(len(self.app.hosts), 1)
        self.assertEqual(self.dp.send_msg.call_count, 2)
        flow = self.dp.send_msg.call_args_list[0].args[0]
        self.assertEqual(flow.instructions[0].actions[0].port, 4)
        self.assertNotEqual(flow.instructions[0].actions[0].port, self.dp.ofproto.OFPP_FLOOD)

    def testLldpAndUnknownHostsNeverFabricateAttachments(self):
        self.app.packetIn(self.event(3, ethertype=0x88CC))
        self.app.packetIn(self.event(3, source={"mac": "02:00:00:00:00:ff", "ipv4": "10.77.0.99"}))
        self.assertEqual(self.app.hosts, {})
        self.dp.send_msg.assert_not_called()

    def testTransitPacketDoesNotDiscoverHost(self):
        self.app.links[("0000000000000004", 1, "0000000000000002", 3)] = {}
        self.app.packetIn(self.event(1))
        self.assertEqual(self.app.hosts, {})


if __name__ == "__main__":
    unittest.main()
