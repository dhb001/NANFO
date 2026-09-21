"""Dependency-free schema contract shared by host tools and the backend image."""

import sys
from pathlib import Path

# Direct `python deploy/manage.py` has deploy/, not backend/, on sys.path.
# Import only the dependency-free contract; never runtime settings or DB factories.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.core.schema_version import CURRENT_SCHEMA, HISTORICAL_MIGRATION_CASES  # noqa: E402

__all__ = ["CURRENT_SCHEMA", "HISTORICAL_MIGRATION_CASES"]
