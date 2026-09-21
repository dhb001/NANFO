"""Deterministic scene fixtures shared by spatial validation and persistence tests."""

import uuid

NETWORK_ID = uuid.UUID(int=301)
WORKSPACE_ID = uuid.UUID(int=302)
ACTOR_ID = uuid.UUID(int=303)
DEVICE_ID = uuid.UUID(int=304)


def spatial_object(object_id="ap", object_type="device", parent_id=None, **changes):
    return {
        "object_id": object_id, "object_type": object_type, "parent_id": parent_id,
        "name": object_id, "position": {"x": 0, "y": 0, "z": 0},
        "rotation": {"x": 0, "y": 0, "z": 0}, "device_id": None,
        "provenance": {"source": "operator-survey", "accuracy_m": None}, **changes,
    }


def scene_payload(objects=None):
    return {"version": 1, "coordinate_system": {"units": "m", "up_axis": "y"},
            "objects": [] if objects is None else objects}


def replace_payload(revision=0, objects=None):
    return {"expected_revision": revision, "scene": scene_payload(objects)}
