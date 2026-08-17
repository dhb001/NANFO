"""Unit tests for network schema adapters."""

from __future__ import annotations

import ipaddress
import uuid
from datetime import UTC, datetime

from app.modules.network.schemas import DeviceResponse


def test_device_response_accepts_ipaddress_instance_from_orm() -> None:
    payload = {
        "device_id": uuid.uuid4(),
        "network_id": uuid.uuid4(),
        "hostname": "edge-1",
        "ip_address": ipaddress.IPv4Address("10.1.1.1"),
        "device_type": "router",
        "vendor": "NANFO",
        "model": "LAB",
        "location_hint": None,
        "spatial_ref_id": None,
        "status": "active",
        "created_at": datetime.now(UTC),
    }

    model = DeviceResponse.model_validate(payload)

    assert model.ip_address == "10.1.1.1"
