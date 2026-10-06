"""Current-source compatibility and historical evidence are different contracts."""

import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from deploy import adr023_checkpoint, backup_restore, manage, verify
from deploy.release_manifest import project_result
from deploy.schema_contract import CURRENT_SCHEMA, migration_head, require_consistent_schema


def checkpoint(schema=CURRENT_SCHEMA):
    return {
        "schema": schema,
        "telemetry_archive": {name: {} for name in (
            "telemetry_archive_receipts", "telemetry_event_tombstones", "telemetry_evidence_pins",
            "telemetry_reference_coverage", "telemetry_reference_reconciliation")},
        "autonomous_execution": {"safe": True, "unreleased_executions": 0},
        "experimental_lab": {"safe": True, "unreleased_runs": 0, "owned_resources": 0, "pending_actions": 0},
    }


def test_explicit_current_contract_matches_entire_chain_and_readiness():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from app.core.runtime_health import SCHEMA_HEAD
    from scripts.verify_measured_twin import ACCEPTANCE_SCHEMA

    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "backend/alembic"))
    scripts = ScriptDirectory.from_config(config)
    assert CURRENT_SCHEMA == SCHEMA_HEAD == "0030"
    assert scripts.get_heads() == [CURRENT_SCHEMA]
    assert [rev.revision for rev in scripts.walk_revisions("base", CURRENT_SCHEMA)] == [
        f"{number:04d}" for number in range(int(CURRENT_SCHEMA), 0, -1)
    ]
    assert scripts.get_revision("0030").down_revision == "0029"
    assert migration_head() == require_consistent_schema() == CURRENT_SCHEMA
    assert ACCEPTANCE_SCHEMA == "0027"  # Historical verifier not silently retargeted.
    assert verify.runtime_source("deploy/schema_contract.py")
    assert verify.runtime_source("backend/app/core/schema_version.py")


@pytest.mark.parametrize("schema", ["0019", "0021", "0024", "0027", "0028", "0029", "0030"])
def test_historical_evidence_names_export_unchanged(schema):
    case = f"migration_{schema}"
    original = json.dumps({"cases": {case: {"status": "passed"}}}).encode()
    assert json.loads(project_result(original))["cases"] == {case: {"status": "passed"}}
    assert (case in verify.CASES) == (schema == CURRENT_SCHEMA)


@pytest.mark.parametrize("schema", ["0027", "0028", "0029", "0030"])
@pytest.mark.parametrize("missing", ["volume", "telemetry_archive", "autonomous_execution"])
def test_archive_safety_floor_cannot_be_bypassed_by_new_revision(schema, missing):
    value = checkpoint(schema)
    volumes = ["telemetry_archive", *(["stream_archive"] if int(schema) >= 30 else [])]
    backup_restore.require_current_archive_checkpoint(value, volumes)
    if missing == "volume":
        volumes = [name for name in volumes if name != "telemetry_archive"]
    else:
        del value[missing]
    with pytest.raises(backup_restore.OperationError, match="0027\\+"):
        backup_restore.require_current_archive_checkpoint(value, volumes)


@pytest.mark.parametrize("schema", ["0030", "0031"])
def test_0030_backup_requires_the_stream_retention_archive(schema):
    backup_restore.require_current_archive_checkpoint(checkpoint("0029"), ["telemetry_archive"])
    with pytest.raises(backup_restore.OperationError, match="0030\\+ requires the stream retention archive"):
        backup_restore.require_current_archive_checkpoint(checkpoint(schema), ["telemetry_archive"])
    backup_restore.require_current_archive_checkpoint(checkpoint(schema), ["telemetry_archive", "stream_archive"])


@pytest.mark.parametrize("field", ["unreleased_runs", "owned_resources", "pending_actions", "missing"])
def test_0028_backup_refuses_experimental_ownership(field):
    value = checkpoint()
    if field == "missing":
        del value["experimental_lab"]
    else:
        value["experimental_lab"][field] = 1
    with pytest.raises(backup_restore.OperationError, match="0028\\+"):
        backup_restore.require_current_archive_checkpoint(value, ["telemetry_archive"])
    # Real0027 archives have no experimental tables/proof, and remain readable.
    value["schema"] = "0027"
    backup_restore.require_current_archive_checkpoint(value, ["telemetry_archive"])


@pytest.mark.parametrize("counts", [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)])
def test_experimental_checkpoint_is_readonly_and_all_ownership_must_be_released(counts):
    db = AsyncMock()
    db.scalar.side_effect = counts
    result = asyncio.run(adr023_checkpoint.experimental_lab_checkpoint(db))
    assert result == {"safe": counts == (0, 0, 0), "unreleased_runs": counts[0],
                      "owned_resources": counts[1], "pending_actions": counts[2]}
    assert all(str(call.args[0]).startswith("SELECT count(*) FROM experimental_lab_")
               for call in db.scalar.call_args_list)
    db.commit.assert_not_called()


@pytest.mark.parametrize("schema", ["0027", "0028", "0029", "0030"])
def test_fresh_start_marks_actual_current_schema_only(tmp_path, monkeypatch, schema):
    config = {"NANFO_PROJECT": "nanfo-deploy-fresh", "NANFO_BACKEND_IMAGE": "backend",
              "NANFO_FRONTEND_IMAGE": "frontend", "NANFO_NEO4J_IMAGE": "neo4j", "NANFO_REDIS_IMAGE": "redis"}
    monkeypatch.setattr(manage, "load_config", lambda _: config)
    commands = Mock(return_value=SimpleNamespace(stdout=json.dumps({"safe": True, "schema": schema})))
    monkeypatch.setattr(manage, "compose", commands)
    monkeypatch.setattr(manage, "run", Mock(return_value=SimpleNamespace(stdout="sha256:image")))
    monkeypatch.setattr("sys.argv", ["manage.py", "--state", str(tmp_path), "start"])
    if schema != CURRENT_SCHEMA:
        with pytest.raises(ValueError, match="initialization schema/checkpoint"):
            manage.main()
        assert not (tmp_path / "initialized.json").exists()
        assert commands.call_args.args[-1] == "checkpoint"
    else:
        manage.main()
        assert json.loads((tmp_path / "initialized.json").read_text())["schema"] == CURRENT_SCHEMA


def test_restore_missing_current_proof_refuses_before_target_mutation(tmp_path, monkeypatch):
    manifest = {"checkpoint": {**checkpoint(), "neo4j_graph": {}},
                "volumes": [{"logical": "telemetry_archive"}]}
    del manifest["checkpoint"]["autonomous_execution"]
    monkeypatch.setattr(backup_restore, "private_directory", lambda path: path)
    monkeypatch.setattr(backup_restore, "load_manifest", lambda *args: copy.deepcopy(manifest))
    deployment = Mock()
    with pytest.raises(backup_restore.OperationError, match="0027\\+"):
        backup_restore.restore(deployment, tmp_path, b"x" * 32, max_bytes=1000)
    deployment.compose.assert_not_called()
    deployment.maintenance.assert_not_called()
