import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.network.deletion import InventoryDependencyRepository
from tests.asset_support import request

DEVICE = uuid.UUID("abcdefab-1234-5678-9abc-abcdef123456")


@pytest.mark.parametrize("key", [str(DEVICE).upper(), DEVICE.hex, "{" + str(DEVICE).upper() + "}", DEVICE.urn])
def test_new_mapping_canonicalizes_uuid_aliases(key):
    assert request(mapping_by_device_id={key: " room ", str(DEVICE): "room"}).mapping_by_device_id == {
        str(DEVICE): "room",
    }


@pytest.mark.parametrize("alias", [str(DEVICE).upper(), DEVICE.hex, "{" + str(DEVICE) + "}"])
def test_equivalent_uuid_conflicting_values_rejected(alias):
    with pytest.raises(ValidationError, match="conflicting"):
        request(mapping_by_device_id={str(DEVICE): "room-a", alias: "room-b"})


@pytest.mark.parametrize("mapping", [{"bad": "room"}, {str(DEVICE): ""}])
def test_invalid_new_mapping_rejected(mapping):
    with pytest.raises(ValidationError):
        request(mapping_by_device_id=mapping)


@pytest.mark.parametrize("mapping", [
    {str(DEVICE).upper(): "room"}, {DEVICE.hex: "room"}, {"{" + str(DEVICE) + "}": "room"},
    {"invalid": "room"}, {str(DEVICE): "one", DEVICE.hex: "two"}, None, [],
])
async def test_legacy_mapping_blocks_without_mutation(mock_db, mapping):
    result = MagicMock()
    result.all.return_value = [(uuid.UUID(int=1), mapping)]
    mock_db.execute.return_value = result
    with pytest.raises(HTTPException) as error:
        await InventoryDependencyRepository(mock_db)._assert_legacy_asset_mappings_safe(uuid.UUID(int=9), DEVICE)
    assert error.value.status_code == 409
    mock_db.flush.assert_not_awaited()
    mock_db.add.assert_not_called()


async def test_legacy_lookup_reaches_mapping_after_first_page(mock_db):
    first, second = MagicMock(), MagicMock()
    first.all.return_value = [(uuid.UUID(int=n), {}) for n in range(1, 201)]
    second.all.return_value = [(uuid.UUID(int=201), {DEVICE.hex: "room"})]
    mock_db.execute.side_effect = [first, second]
    with pytest.raises(HTTPException) as error:
        await InventoryDependencyRepository(mock_db)._assert_legacy_asset_mappings_safe(uuid.UUID(int=9), DEVICE)
    assert error.value.status_code == 409 and mock_db.execute.await_count == 2
