"""Fresh source/restore proxy pools must never overlap existing host networks."""

import ipaddress
import json
from unittest.mock import Mock

import pytest

from deploy import manage, verify


def inventory(monkeypatch, pools, routes):
    command = Mock(side_effect=[
        Mock(stdout="network-id\n"),
        Mock(stdout=json.dumps([{"IPAM": {"Config": None}}, {"IPAM": {"Config": [{"Subnet": value} for value in pools]}}])),
        Mock(stdout=json.dumps([{"dst": value} for value in routes])),
    ])
    monkeypatch.setattr(manage, "run", command)
    monkeypatch.setattr(manage.secrets, "randbelow", lambda size: 0)
    return command


def test_source_restore_avoid_docker_pools_and_host_routes(monkeypatch):
    command = inventory(monkeypatch, ["10.0.0.0/24", "fd00::/64"], ["default", "10.0.1.0/24"])
    source, restore = manage.allocate_proxy_networks(2)
    assert source["NANFO_PROXY_SUBNET"] == "10.0.2.0/24"
    assert restore["NANFO_PROXY_SUBNET"] == "10.0.3.0/24"
    for value in (source, restore):
        assert ipaddress.ip_address(value["NANFO_PROXY_GATEWAY_IP"]) in ipaddress.ip_network(value["NANFO_PROXY_SUBNET"])
        assert value["NANFO_PROXY_GATEWAY_IP"].endswith(".254")
    assert all("create" not in call.args[0] for call in command.call_args_list)


def test_exhausted_private_routes_refuse_without_mutation(monkeypatch):
    inventory(monkeypatch, [], ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"])
    with pytest.raises(ValueError, match="No unused private proxy subnet"):
        manage.allocate_proxy_networks(2)


def test_inventory_failure_does_not_fall_back_to_shared_default(monkeypatch):
    monkeypatch.setattr(manage, "run", Mock(side_effect=OSError))
    with pytest.raises(OSError):
        manage.allocate_proxy_networks()


def test_gateway_address_does_not_collide_with_first_serving_apis(monkeypatch):
    inventory(monkeypatch, [], [])
    proxy = manage.allocate_proxy_networks()[0]
    subnet = ipaddress.ip_network(proxy["NANFO_PROXY_SUBNET"])
    dynamic_api_addresses = {str(subnet.network_address + offset) for offset in (2, 3)}
    assert proxy["NANFO_PROXY_GATEWAY_IP"] not in dynamic_api_addresses


def test_concurrent_authors_require_explicit_drift_detection():
    args = verify.parse_args(["--live", "--detect-source-drift"])
    assert args.detect_source_drift and not args.agents_idle
    with pytest.raises(SystemExit):
        verify.parse_args(["--live"])
