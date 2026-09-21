"""Unit tests for network schema adapters."""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.modules.network.schemas import (
    DeviceResponse,
    UpsertCampusModelAssetRequest,
    UpsertDeviceGroupInput,
    UpsertDeviceGroupsRequest,
)


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


def test_upsert_campus_model_asset_request_validates_integrity() -> None:
    model_bytes = b"nanfo-campus-model"
    payload = {
        "model_file_name": "campus.glb",
        "model_mime_type": "model/gltf-binary",
        "model_data_base64": base64.b64encode(model_bytes).decode("ascii"),
        "model_sha256": hashlib.sha256(model_bytes).hexdigest(),
        "model_size_bytes": len(model_bytes),
        "mapping_by_device_id": {
            str(uuid.uuid4()): "strathmore/sbs/f01/core/router-1",
        },
        "source": "manual_upload",
        "replace_existing": True,
    }

    req = UpsertCampusModelAssetRequest.model_validate(payload)

    assert req.model_file_name == "campus.glb"
    assert req.model_sha256 == payload["model_sha256"]
    assert req.model_size_bytes == len(model_bytes)


def test_upsert_campus_model_asset_request_rejects_sha_mismatch() -> None:
    model_bytes = b"nanfo-campus-model"
    with pytest.raises(ValidationError):
        UpsertCampusModelAssetRequest.model_validate(
            {
                "model_file_name": "campus.glb",
                "model_mime_type": "model/gltf-binary",
                "model_data_base64": base64.b64encode(model_bytes).decode("ascii"),
                "model_sha256": "0" * 64,
                "model_size_bytes": len(model_bytes),
                "mapping_by_device_id": {},
            }
        )


def test_upsert_device_group_input_normalizes_and_deduplicates_device_ids() -> None:
    device_id = uuid.uuid4()
    parsed = UpsertDeviceGroupInput.model_validate(
        {
            "group_key": " Floor 2 Wireless ",
            "name": "Floor 2 Wireless",
            "group_type": "functional",
            "selector": {"functional_group": "wireless"},
            "device_ids": [str(device_id), str(device_id)],
        }
    )

    assert parsed.group_key == "floor-2-wireless"
    assert parsed.device_ids == [device_id]


def test_upsert_device_group_input_requires_selector_or_device_ids() -> None:
    with pytest.raises(ValidationError):
        UpsertDeviceGroupInput.model_validate(
            {
                "group_key": "empty-group",
                "name": "Empty Group",
                "group_type": "custom",
                "selector": {},
                "device_ids": [],
            }
        )


def test_upsert_device_groups_request_rejects_duplicate_group_key() -> None:
    device_id = str(uuid.uuid4())
    with pytest.raises(ValidationError):
        UpsertDeviceGroupsRequest.model_validate(
            {
                "groups": [
                    {
                        "group_key": "floor-2-wireless",
                        "name": "One",
                        "group_type": "functional",
                        "selector": {"functional_group": "wireless"},
                        "device_ids": [device_id],
                    },
                    {
                        "group_key": "floor-2-wireless",
                        "name": "Two",
                        "group_type": "functional",
                        "selector": {"functional_group": "wireless"},
                        "device_ids": [device_id],
                    },
                ]
            }
        )
