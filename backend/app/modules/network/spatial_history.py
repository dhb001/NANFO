"""Spatial scene history storage: full checkpoints plus object-level deltas (ADR-028, F18).

Scene revisions used to store a full JSON copy per edit. When the history table has
the delta columns (migration 0030: ``delta``, ``base_revision``, ``storage_kind`` and
a nullable ``scene``), a revision is stored as a *delta* against the revision directly
before it, and a *full* checkpoint is written every :data:`CHECKPOINT_INTERVAL`
revisions (or whenever a delta would not be smaller than the scene). Reads rebuild a
revision from the nearest checkpoint at or below it by applying at most
``CHECKPOINT_INTERVAL - 1`` deltas, so API responses are unchanged.

Delta document (JSONB), keyed by object id; arrays carry every ordering because
JSONB does not preserve object key order::

    {"format": 1,
     "meta": {<every scene key except "objects">},
     "object_count": <int>,
     "removed": [<object_id>, ...],
     "changed": {<object_id>: <object>, ...},
     "added": {<object_id>: <object>, ...},
     "added_order": [<object_id>, ...],
     "order": [<object_id>, ...]}          # only when not the natural order

Natural order = base order without removed ids, followed by ``added_order``.
This module is pure (no I/O); every malformed input raises :class:`SceneHistoryError`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

#: A full scene is written for every revision divisible by this interval.
CHECKPOINT_INTERVAL = 20
DELTA_FORMAT = 1
_DELTA_KEYS = frozenset({"format", "meta", "object_count", "removed", "changed", "added", "added_order", "order"})


class SceneHistoryError(ValueError):
    """Stored history cannot be (re)constructed; never repaired silently."""


def is_checkpoint(revision: int) -> bool:
    return revision % CHECKPOINT_INTERVAL == 0


def _json_size(value: Any) -> int:
    return len(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False))


def _indexed(scene: Mapping[str, Any]) -> tuple[list[str], dict[str, dict]]:
    objects = scene.get("objects")
    if not isinstance(objects, list):
        raise SceneHistoryError("scene objects must be a list")
    order: list[str] = []
    by_id: dict[str, dict] = {}
    for item in objects:
        if not isinstance(item, dict) or not isinstance(item.get("object_id"), str):
            raise SceneHistoryError("scene object requires a string object_id")
        if item["object_id"] in by_id:
            raise SceneHistoryError("scene object ids must be unique")
        order.append(item["object_id"])
        by_id[item["object_id"]] = item
    return order, by_id


def _meta(scene: Mapping[str, Any]) -> dict:
    return {key: value for key, value in scene.items() if key != "objects"}


def compute_scene_delta(base: Mapping[str, Any], scene: Mapping[str, Any]) -> dict:
    """Object-level delta turning ``base`` into ``scene`` (both JSON-mode scenes)."""
    base_order, base_objects = _indexed(base)
    order, objects = _indexed(scene)
    removed = [object_id for object_id in base_order if object_id not in objects]
    changed = {object_id: objects[object_id] for object_id in order
               if object_id in base_objects and base_objects[object_id] != objects[object_id]}
    added_order = [object_id for object_id in order if object_id not in base_objects]
    delta = {
        "format": DELTA_FORMAT, "meta": _meta(scene), "object_count": len(order), "removed": removed,
        "changed": changed, "added": {object_id: objects[object_id] for object_id in added_order},
        "added_order": added_order,
    }
    removed_ids = set(removed)
    if [object_id for object_id in base_order if object_id not in removed_ids] + added_order != order:
        delta["order"] = order
    return delta


def delta_saves_space(delta: Mapping[str, Any], scene: Mapping[str, Any]) -> bool:
    """Store a delta only when it is strictly smaller than the full scene."""
    return _json_size(delta) < _json_size(scene)


def _id_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise SceneHistoryError(f"delta {name} must be a list of object ids")
    if len(set(value)) != len(value):
        raise SceneHistoryError(f"delta {name} repeats an object id")
    return value


def _objects(value: Any, name: str) -> dict[str, dict]:
    if not isinstance(value, dict):
        raise SceneHistoryError(f"delta {name} must map object ids to objects")
    for object_id, item in value.items():
        if not isinstance(item, dict) or item.get("object_id") != object_id:
            raise SceneHistoryError(f"delta {name} entries must be keyed by their object_id")
    return value


def apply_scene_delta(base: Mapping[str, Any], delta: Mapping[str, Any]) -> dict:
    """Rebuild the scene a delta describes; strict, never partially applied."""
    if not isinstance(delta, Mapping) or delta.get("format") != DELTA_FORMAT or not set(delta) <= _DELTA_KEYS:
        raise SceneHistoryError("unsupported scene delta format")
    meta = delta.get("meta")
    if not isinstance(meta, dict) or "objects" in meta:
        raise SceneHistoryError("delta meta must be the scene without objects")
    base_order, objects = _indexed(base)
    objects = dict(objects)
    removed = _id_list(delta.get("removed"), "removed")
    added_order = _id_list(delta.get("added_order"), "added_order")
    changed = _objects(delta.get("changed"), "changed")
    added = _objects(delta.get("added"), "added")
    if set(added) != set(added_order):
        raise SceneHistoryError("delta added objects and added_order disagree")
    if not set(removed) <= objects.keys():
        raise SceneHistoryError("delta removes an object the base does not contain")
    for object_id in removed:
        del objects[object_id]
    if not changed.keys() <= objects.keys():
        raise SceneHistoryError("delta changes an object the base does not contain")
    if added.keys() & objects.keys():
        raise SceneHistoryError("delta adds an object that already exists")
    objects.update(changed)
    objects.update(added)
    if "order" in delta:
        order = _id_list(delta["order"], "order")
    else:
        removed_ids = set(removed)
        order = [object_id for object_id in base_order if object_id not in removed_ids] + added_order
    if set(order) != objects.keys() or len(order) != len(objects):
        raise SceneHistoryError("delta order does not cover the rebuilt objects exactly")
    if delta.get("object_count") != len(order):
        raise SceneHistoryError("delta object_count mismatch")
    return {**meta, "objects": [objects[object_id] for object_id in order]}


def reconstruct(rows: Sequence[Mapping[str, Any]], revision: int) -> dict:
    """Rebuild ``revision`` from ascending rows starting at its nearest checkpoint.

    ``rows`` carry ``revision``, ``storage_kind``, ``scene``, ``delta`` and
    ``base_revision``. The first row must be a full checkpoint, every later row a
    delta whose ``base_revision`` is the row before it, and the last row must be
    ``revision`` itself.
    """
    if not rows or rows[-1]["revision"] != revision:
        raise SceneHistoryError("requested revision is missing from its checkpoint chain")
    first = rows[0]
    if first["storage_kind"] != "full" or not isinstance(first["scene"], dict):
        raise SceneHistoryError("history chain does not start at a full checkpoint")
    scene = first["scene"]
    previous = first["revision"]
    for row in rows[1:]:
        if row["storage_kind"] != "delta" or row["base_revision"] != previous or row["revision"] != previous + 1:
            raise SceneHistoryError("history delta chain is not contiguous")
        scene = apply_scene_delta(scene, row["delta"])
        previous = row["revision"]
    return scene
