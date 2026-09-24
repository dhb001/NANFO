"""ADR-028 F18: spatial scene history as full checkpoints plus object-level deltas."""

import copy
import json
import random
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.network import spatial_history
from app.modules.network.spatial_history import (
    CHECKPOINT_INTERVAL,
    SceneHistoryError,
    apply_scene_delta,
    compute_scene_delta,
    delta_saves_space,
    is_checkpoint,
    reconstruct,
)
from app.modules.network.spatial_repository import SpatialSceneRepository
from app.modules.network.spatial_schemas import SpatialHistoryQuery, SpatialSceneInput
from tests.spatial_support import NETWORK_ID, scene_payload, spatial_object

ACTOR = uuid.UUID(int=77)


def scene(*object_ids, **changes):
    return SpatialSceneInput.model_validate(scene_payload([
        spatial_object(object_id, name=changes.get(object_id, object_id)) for object_id in object_ids
    ])).model_dump(mode="json")


def jsonb(value):
    """Round-trip like PostgreSQL JSONB: object key order is not preserved."""
    def shuffle(item):
        if isinstance(item, dict):
            return {key: shuffle(item[key]) for key in sorted(item, key=lambda k: (len(k), k), reverse=True)}
        if isinstance(item, list):
            return [shuffle(element) for element in item]
        return item
    return shuffle(json.loads(json.dumps(value)))


@pytest.mark.parametrize("before,after", [
    (("a", "b", "c"), ("a", "b", "c")),              # unchanged content
    (("a", "b", "c"), ("a", "c")),                    # removal
    (("a", "b"), ("a", "b", "z", "y")),               # appends keep their order
    (("a", "b", "c"), ("c", "a", "b")),               # reorder
    (("a", "c"), ("a", "b", "c")),                    # insertion in the middle
    ((), ("a",)),                                     # first object
    (("a", "b"), ()),                                 # everything removed
])
def test_delta_round_trips_exactly_through_jsonb(before, after):
    base, target = scene(*before), scene(*after, b="renamed")
    delta = compute_scene_delta(base, target)
    assert apply_scene_delta(jsonb(base), jsonb(delta)) == target
    assert delta["object_count"] == len(after)
    assert set(delta["changed"]) <= set(before) and set(delta["added"]) == set(after) - set(before)


def test_natural_order_is_not_stored_and_changes_carry_only_touched_objects():
    base = scene(*[f"o{n}" for n in range(50)])
    target = copy.deepcopy(base)
    target["objects"][7]["name"] = "moved"
    target["objects"].append(spatial_object("new"))
    target["objects"] = [obj for obj in target["objects"] if obj["object_id"] != "o3"]
    delta = compute_scene_delta(base, target)
    assert "order" not in delta
    assert list(delta["changed"]) == ["o7"] and delta["removed"] == ["o3"] and delta["added_order"] == ["new"]
    assert delta_saves_space(delta, target)
    assert apply_scene_delta(base, delta) == target


def test_total_rewrite_is_not_worth_a_delta():
    base, target = scene("a", "b"), scene("c", "d")
    assert not delta_saves_space(compute_scene_delta(base, target), target)


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(format=2),
    lambda d: d.update(unexpected=True),
    lambda d: d.update(removed=["missing"]),
    lambda d: d.update(changed={"missing": spatial_object("missing")}),
    lambda d: d.update(changed={"a": spatial_object("other")}),
    lambda d: d.update(added={"a": spatial_object("a")}, added_order=["a"]),
    lambda d: d.update(added_order=["x", "y"]),
    lambda d: d.update(order=["a"]),
    lambda d: d.update(order=["a", "a", "b", "x"]),
    lambda d: d.update(object_count=99),
    lambda d: d.update(meta={"objects": []}),
    lambda d: d.update(removed="a"),
])
def test_malformed_deltas_are_rejected_never_partially_applied(mutate):
    base = scene("a", "b")
    delta = compute_scene_delta(base, scene("a", "b", "x", b="renamed"))
    mutate(delta)
    snapshot = copy.deepcopy(base)
    with pytest.raises(SceneHistoryError):
        apply_scene_delta(base, delta)
    assert base == snapshot


def chain_rows(scenes, start=0):
    rows = [{"revision": start, "storage_kind": "full", "scene": scenes[0], "delta": None, "base_revision": None}]
    for offset, target in enumerate(scenes[1:], start=1):
        rows.append({"revision": start + offset, "storage_kind": "delta", "scene": None,
                     "delta": jsonb(compute_scene_delta(scenes[offset - 1], target)),
                     "base_revision": start + offset - 1})
    return rows


def test_seeded_edit_sequences_rebuild_every_revision_from_its_checkpoint():
    rng = random.Random(28)
    current = scene("root")
    scenes = [current]
    for step in range(1, 60):
        objects = [dict(obj) for obj in current["objects"]]
        action = rng.choice(["add", "rename", "remove", "shuffle"])
        if action == "add" or len(objects) < 2:
            objects.insert(rng.randrange(len(objects) + 1), spatial_object(f"n{step}"))
        elif action == "rename":
            objects[rng.randrange(len(objects))]["name"] = f"renamed-{step}"
        elif action == "remove":
            objects.pop(rng.randrange(len(objects)))
        else:
            rng.shuffle(objects)
        current = SpatialSceneInput.model_validate({**current, "objects": objects}).model_dump(mode="json")
        scenes.append(current)
    for checkpoint in range(0, 60, CHECKPOINT_INTERVAL):
        segment = scenes[checkpoint:checkpoint + CHECKPOINT_INTERVAL]
        rows = chain_rows(segment, start=checkpoint)
        for index in range(len(segment)):
            assert reconstruct(rows[:index + 1], checkpoint + index) == segment[index]


@pytest.mark.parametrize("breakage", ["no_checkpoint", "gap", "wrong_base", "missing_tail", "full_in_middle"])
def test_broken_chains_fail_closed(breakage):
    rows = chain_rows([scene("a"), scene("a", "b"), scene("a", "b", "c")], start=40)
    target = 42
    if breakage == "no_checkpoint":
        rows = rows[1:]
    elif breakage == "gap":
        rows = [rows[0], rows[2]]
    elif breakage == "wrong_base":
        rows[2]["base_revision"] = 40
    elif breakage == "missing_tail":
        target = 43
    else:
        rows[1]["storage_kind"] = "full"
    with pytest.raises(SceneHistoryError):
        reconstruct(rows, target)


def test_checkpoint_interval_is_twenty():
    assert CHECKPOINT_INTERVAL == 20
    assert [revision for revision in range(0, 61) if is_checkpoint(revision)] == [0, 20, 40, 60]


# ------------------------------------------------------------------ repository


def delta_db(*, enabled):
    db = AsyncMock()
    db.info = {}
    probe = MagicMock()
    names = [("scene", not enabled), ("network_id", True), ("revision", True)]
    if enabled:
        names += [("delta", False), ("base_revision", False), ("storage_kind", True)]
    probe.all.return_value = [SimpleNamespace(name=name, not_null=not_null) for name, not_null in names]
    db.execute.return_value = probe
    return db


def inserted(db):
    statement = db.execute.await_args_list[-1].args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    return str(compiled), compiled.params


async def test_capability_is_probed_once_per_session_and_requires_nullable_scene():
    db = delta_db(enabled=True)
    repo = SpatialSceneRepository(db)
    assert await repo.delta_history_enabled() is True
    assert await SpatialSceneRepository(db).delta_history_enabled() is True
    assert db.execute.await_count == 1
    assert "to_regclass('network_spatial_scene_revisions')" in str(db.execute.await_args.args[0])
    assert await SpatialSceneRepository(delta_db(enabled=False)).delta_history_enabled() is False
    partial = delta_db(enabled=True)
    partial.execute.return_value.all.return_value = [SimpleNamespace(name="scene", not_null=True),
                                                     SimpleNamespace(name="delta", not_null=False)]
    assert await SpatialSceneRepository(partial).delta_history_enabled() is False


async def test_without_the_0030_columns_every_revision_stays_a_full_copy():
    db = delta_db(enabled=False)
    await SpatialSceneRepository(db).append_revision(NETWORK_ID, 7, scene("a"), ACTOR)
    sql, params = inserted(db)
    assert sql.startswith("INSERT INTO network_spatial_scene_revisions (network_id, revision, scene, actor_id, origin)")
    assert "storage_kind" not in sql and "delta" not in sql
    assert params["origin"] == "replacement" and params["scene"] == scene("a")


async def test_checkpoint_revisions_are_full_and_others_are_deltas_against_the_previous_revision():
    db = delta_db(enabled=True)
    repo = SpatialSceneRepository(db)
    await repo.append_revision(NETWORK_ID, 20, scene("a"), ACTOR)
    sql, params = inserted(db)
    assert params["storage_kind"] == "full" and params["scene"] == scene("a") and "base_revision" not in sql
    base = scene(*[f"o{n}" for n in range(30)])
    target = copy.deepcopy(base)
    target["objects"][4]["name"] = "edited"
    repo._rebuild = AsyncMock(return_value=base)
    await repo.append_revision(NETWORK_ID, 21, target, ACTOR)
    repo._rebuild.assert_awaited_once_with(NETWORK_ID, 20)
    sql, params = inserted(db)
    assert params["storage_kind"] == "delta" and params["scene"] is None and params["base_revision"] == 20
    assert list(params["delta"]["changed"]) == ["o4"] and params["delta"]["object_count"] == 30


@pytest.mark.parametrize("base", ["missing", "broken", "rewrite"])
async def test_unusable_bases_write_a_new_full_checkpoint(base):
    db = delta_db(enabled=True)
    repo = SpatialSceneRepository(db)
    repo._rebuild = AsyncMock(return_value=scene("x", "y"))
    if base == "missing":
        repo._rebuild.return_value = None
    elif base == "broken":
        repo._rebuild.side_effect = SceneHistoryError("gap")
    await repo.append_revision(NETWORK_ID, 5, scene("p", "q"), ACTOR)
    sql, params = inserted(db)
    assert params["storage_kind"] == "full" and params["scene"] == scene("p", "q")


async def test_revision_reads_rebuild_from_the_nearest_checkpoint():
    db = delta_db(enabled=True)
    repo = SpatialSceneRepository(db)
    await repo.delta_history_enabled()
    scenes = [scene("a"), scene("a", "b"), scene("b", "c")]
    rows = chain_rows(scenes, start=60)
    chain = MagicMock()
    chain.mappings.return_value.all.return_value = rows
    db.execute.return_value = chain
    document = await repo.get_revision(NETWORK_ID, 62)
    assert document.revision == 62 and document.model_dump(mode="json", exclude={"revision"}) == scenes[2]
    sql = str(db.execute.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert "max(network_spatial_scene_revisions.revision)" in sql and "storage_kind" in sql
    # Absent revision -> None (404 upstream); present-but-unreachable -> integrity error.
    chain.mappings.return_value.all.return_value = []
    db.scalar = AsyncMock(return_value=None)
    assert await repo.get_revision(NETWORK_ID, 99) is None
    db.scalar.return_value = 99
    with pytest.raises(SceneHistoryError):
        await repo.get_revision(NETWORK_ID, 99)


async def test_history_listing_reads_delta_object_counts_without_rebuilding():
    db = delta_db(enabled=True)
    repo = SpatialSceneRepository(db)
    await repo.delta_history_enabled()
    listing = MagicMock()
    listing.mappings.return_value.all.return_value = [{"total": 0, "revision": None}]
    db.execute.return_value = listing
    result = await repo.list_history(NETWORK_ID, SpatialHistoryQuery(page=1, page_size=5))
    assert result.model_dump() == {"items": [], "total": 0, "page": 1, "page_size": 5}
    sql = str(db.execute.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert "CASE WHEN (network_spatial_scene_revisions.storage_kind =" in sql
    assert "network_spatial_scene_revisions.delta ->>" in sql and "jsonb_array_length" in sql


def test_module_is_pure():
    source = open(spatial_history.__file__, encoding="utf-8").read()
    assert "sqlalchemy" not in source and "import asyncio" not in source
