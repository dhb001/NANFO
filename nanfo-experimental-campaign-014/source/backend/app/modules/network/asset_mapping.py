"""Canonical device identities for new asset mappings and read-only legacy checks."""

import uuid


def normalize_asset_device_mapping(value: dict[str, str]) -> dict[str, str]:
    if not isinstance(value, dict) or len(value) > 10_000:
        raise ValueError("mapping_by_device_id must be an object with at most 10000 items")
    normalized: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise ValueError("mapping_by_device_id keys and values must be strings")
        key, item = key.strip(), item.strip()
        if not key or len(key) > 120:
            raise ValueError("mapping_by_device_id keys must be nonempty and <= 120 characters")
        if not item or len(item) > 240:
            raise ValueError("mapping_by_device_id values must be nonempty and <= 240 characters")
        try:
            identity = str(uuid.UUID(key))
        except ValueError as exc:
            raise ValueError("mapping_by_device_id keys must be valid device UUIDs") from exc
        if identity in normalized and normalized[identity] != item:
            raise ValueError("mapping_by_device_id has conflicting values for equivalent device UUIDs")
        normalized[identity] = item
    return normalized
