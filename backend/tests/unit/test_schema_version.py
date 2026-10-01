"""ADR-028: the code's schema head tracks the single Alembic head (migration 0030).

Readiness (``runtime_health.SCHEMA_HEAD``), deployment initialization and the live
verifiers all migrate to / require ``CURRENT_SCHEMA``; archived release matrices keep
their earlier ``migration_<head>`` cases exportable via ``HISTORICAL_MIGRATION_CASES``.
"""

from __future__ import annotations

import re
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core import runtime_health
from app.core.schema_version import CURRENT_SCHEMA, HISTORICAL_MIGRATION_CASES

BACKEND = Path(__file__).resolve().parents[2]
ACCEPTED_EVIDENCE = BACKEND.parent / "docs/project/ReviewClosureEvidence/accepted/deployment/result-status.json"


def _scripts() -> ScriptDirectory:
    config = Config()
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return ScriptDirectory.from_config(config)


def test_current_schema_is_the_single_alembic_head():
    scripts = _scripts()
    assert CURRENT_SCHEMA == "0030"
    assert scripts.get_heads() == [CURRENT_SCHEMA]
    assert scripts.get_revision(CURRENT_SCHEMA).down_revision == "0029"


def test_readiness_requires_exactly_the_current_head():
    assert runtime_health.SCHEMA_HEAD == CURRENT_SCHEMA


def test_previous_heads_remain_historical_cases_but_the_current_one_is_live():
    assert "migration_0029" in HISTORICAL_MIGRATION_CASES
    assert f"migration_{CURRENT_SCHEMA}" not in HISTORICAL_MIGRATION_CASES
    assert all(re.fullmatch(r"migration_\d{4}", case) and case[-4:] < CURRENT_SCHEMA
               for case in HISTORICAL_MIGRATION_CASES)


def test_accepted_release_matrix_cases_stay_exportable():
    # The accepted deployment evidence (not rewritten, ADR-028 §1) names migration cases
    # of its own head; each must be either the live case or a declared historical one.
    cases = set(re.findall(r"migration_\d{4}", ACCEPTED_EVIDENCE.read_text(encoding="utf-8")))
    assert cases, "accepted evidence must name its migration case"
    assert cases <= {*HISTORICAL_MIGRATION_CASES, f"migration_{CURRENT_SCHEMA}"}
