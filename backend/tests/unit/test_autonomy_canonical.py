"""ADR-028 fix 12/11: shared canonical hashing is byte-identical; app code never imports scripts.*."""

import hashlib
import json
import math
import os
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.canonical import canonical_json_bytes, canonical_sha256
from app.modules.autonomy.calibration_verification import backlog_reading_digest
from app.modules.autonomy.receiver_health import ReceiverHealth
from app.modules.autonomy.safety import safety_input_digest
from app.modules.autonomy.schemas import OperationalSettings, Proposal, canonical_json, contract_digest

BACKEND = Path(__file__).resolve().parents[2]

VALUES = [
    {"b": [3, 2.5, -0.0, 1e-300, 12345678901234567890], "a": {"z": None, "y": True}, "ü": "naïve ✓"},
    [],
    {"nested": [{"k": "v", "n": [1, [2, [3]]]}], "emoji": "\U0001f600", "ctrl": "\x00\x1f\"\\"},
    "plain",
    0.1 + 0.2,
]


def historical_text(value):
    """The exact pre-ADR-028 encoding used by every replaced call site."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


@pytest.mark.parametrize("value", VALUES)
def test_core_helpers_are_byte_identical_to_historical_encoding(value):
    assert canonical_json_bytes(value) == historical_text(value).encode()
    assert canonical_json_bytes(value) == historical_text(value).encode("utf-8")
    assert canonical_sha256(value) == hashlib.sha256(historical_text(value).encode()).hexdigest()
    assert ReceiverHealth.canonical(value) == historical_text(value).encode()


@pytest.mark.parametrize("value", [math.nan, math.inf, {"x": -math.inf}])
def test_non_finite_values_still_fail_closed(value):
    with pytest.raises(ValueError):
        canonical_json_bytes(value)
    with pytest.raises(ValueError):
        historical_text(value)


def test_contract_digest_and_canonical_json_unchanged_for_models():
    proposal = Proposal(action_id="route-ü", checkpoint_sha256="a" * 64, observation_contract="c.v1",
                        evidence=["x:1", "naïve"])
    text = json.dumps(proposal.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False)
    assert canonical_json(proposal) == text
    assert contract_digest(proposal) == hashlib.sha256(text.encode("utf-8")).hexdigest()
    settings = OperationalSettings()
    assert contract_digest(settings) == hashlib.sha256(historical_text(settings.model_dump(mode="json")).encode()).hexdigest()


def test_safety_input_digest_matches_historical_formula():
    from tests.unit.test_autonomy_safety import inputs

    data = inputs.__wrapped__()
    routes = data["action"]["routes"]
    from app.modules.autonomy.safety import DemandRoute, SafetyObservation

    payload = {"observation": SafetyObservation.model_validate(data["observation"]).model_dump(mode="json"),
               "routes": [DemandRoute.model_validate(r).model_dump(mode="json")
                          for r in sorted(routes, key=lambda r: (r["demand_id"], r["route_id"]))]}
    assert safety_input_digest(data["observation"], routes) == hashlib.sha256(historical_text(payload).encode("utf-8")).hexdigest()


def test_backlog_reading_digest_matches_historical_formula():
    body = {"reading_id": str(uuid.uuid4()), "queues": [{"egress_id": "a", "backlog": 1.5, "native_backlog_evidence": {"x": 1}},
                                                        {"egress_id": "b", "backlog": 0}]}
    reading = SimpleNamespace(model_dump=lambda mode: json.loads(json.dumps(body)))
    expected = json.loads(json.dumps(body))
    for queue in expected["queues"]:
        queue.pop("native_backlog_evidence", None)
    assert backlog_reading_digest(reading) == hashlib.sha256(historical_text(expected).encode()).hexdigest()


def test_frozen_runner_alias_is_the_shared_helper():
    from scripts.frozen_model_diagnostic import canonical_hash, load_registry, select_model

    from app.modules.autonomy import model_diagnostic_registry
    assert canonical_hash is canonical_sha256
    assert load_registry is model_diagnostic_registry.load_registry
    assert select_model is model_diagnostic_registry.select_model


OWNED = [path for path in (BACKEND / "app/modules/autonomy").glob("*.py")
         if path.name not in {"campaign_evidence.py", "qualification.py", "models.py", "queries.py"}] + [
    BACKEND / "app/api/v1/autonomy.py", BACKEND / "app/api/v1/autonomy_controls.py",
    BACKEND / "app/api/v1/model_diagnostics.py"]


@pytest.mark.parametrize("path", OWNED, ids=lambda path: path.name)
def test_owned_application_code_never_imports_scripts(path):
    source = path.read_text()
    assert "from scripts" not in source and "import scripts" not in source


def test_application_import_loads_no_scripts_or_emulation_modules():
    root = BACKEND.parent
    code = ("import app.main, sys; print(','.join(sorted(k for k in sys.modules "
            "if k == 'scripts' or k.startswith(('scripts.', 'emulation')))))")
    result = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, check=True, cwd=BACKEND,
                            env={**os.environ, "PYTHONPATH": str(BACKEND) + os.pathsep + str(root),
                                 "PYTHONDONTWRITEBYTECODE": "1"})
    assert result.stdout.strip() == ""


# ── Fix 11b: experimental/lab wiring is lazy; the lab flag never unpins historical evidence ──

#: The only emulation modules owned code may load at import time: stdlib-only shared contract
#: modules that never import a driver, the lab runtime or application code (FRR wire constants;
#: C15 lab contracts reached through Intent's lab mailbox).
PURE_EMULATION_CONTRACTS = {"emulation", "emulation.autonomous_contract", "emulation.lab_contracts"}


def run_clean(code):
    """Run in a fresh interpreter (the pytest process may already hold lab modules)."""
    root = BACKEND.parent
    env = {key: value for key, value in os.environ.items() if key != "NANFO_EXPERIMENTAL_LAB_ENABLED"}
    result = subprocess.run([sys.executable, "-B", "-c", textwrap.dedent(code)], capture_output=True, text=True,
                            check=True, cwd=BACKEND, env={**env, "PYTHONPATH": str(BACKEND) + os.pathsep + str(root),
                                                          "PYTHONDONTWRITEBYTECODE": "1"})
    return json.loads(result.stdout)


def test_owned_modules_import_no_experimental_lab_or_driver_code():
    modules = [f"app.modules.autonomy.{path.stem}" for path in OWNED
               if path.parent.name == "autonomy" and path.stem != "__init__"]
    modules += ["app.api.v1.autonomy", "app.api.v1.autonomy_controls", "app.api.v1.model_diagnostics"]
    assert "app.modules.autonomy.service" in modules and "app.modules.autonomy.execution_composition" in modules
    loaded = run_clean(f"""
        import importlib, json, sys
        for name in {modules!r}:
            importlib.import_module(name)
        print(json.dumps(sorted(k for k in sys.modules if k == "scripts"
                                or k.startswith(("scripts.", "emulation", "app.modules.autonomy.experimental")))))
    """)
    assert set(loaded) <= PURE_EMULATION_CONTRACTS, loaded


def test_experimental_references_are_lazy_and_not_gated_off_by_the_lab_flag():
    """Formal stages never import experimental code. With NANFO_EXPERIMENTAL_LAB_ENABLED off, rows
    written while the lab was enabled are still enumerated, so their telemetry pins survive."""
    loaded = run_clean("""
        import asyncio, json, sys, uuid

        from app.core.config import get_settings
        from app.modules.autonomy.service import telemetry_reference_page

        class Rows:
            def all(self):
                return []

        class Database:
            def __init__(self):
                self.experimental_queries = 0

            async def scalar(self, query):
                return "present"

            async def scalars(self, query):
                return Rows()

            async def execute(self, query):
                self.experimental_queries += 1
                return Rows()

        async def main():
            assert get_settings().NANFO_EXPERIMENTAL_LAB_ENABLED is False
            db, cursor, loaded = Database(), None, []
            for _ in range(9):
                page = await telemetry_reference_page(db, workspace_id=uuid.uuid4(), after=cursor, limit=10)
                loaded.append(sorted(k for k in sys.modules if k.startswith("app.modules.autonomy.experimental")))
                cursor = page.next_cursor
            assert cursor is None and db.experimental_queries == 3
            print(json.dumps(loaded))

        asyncio.run(main())
    """)
    assert loaded[:6] == [[]] * 6
    assert {"app.modules.autonomy.experimental.models", "app.modules.autonomy.experimental.references"} <= set(loaded[6])
