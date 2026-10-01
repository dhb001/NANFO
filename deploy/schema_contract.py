"""Dependency-free schema contract shared by host tools and the backend image.

``CURRENT_SCHEMA`` stays centralised in ``backend/app/core/schema_version.py`` (readiness,
initializer, maintenance, manage.py markers and the verifier agree on it).
``migration_head()`` reads the single Alembic head from the migration files without
importing Alembic or settings. Fresh initialization refuses to run when the backend
contract lags the head (ADR-028 head: 0030), because ``alembic upgrade CURRENT_SCHEMA``
would otherwise silently stop below the schema the shipped code requires.
"""

import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
VERSIONS = BACKEND / "alembic" / "versions"
# Direct `python deploy/manage.py` has deploy/, not backend/, on sys.path.
# Import only the dependency-free contract; never runtime settings or DB factories.
sys.path.insert(0, str(BACKEND))
from app.core.schema_version import CURRENT_SCHEMA, HISTORICAL_MIGRATION_CASES  # noqa: E402

_REVISION = re.compile(r"^revision(?:\s*:\s*[^=]+)?\s*=\s*[\"']([0-9A-Za-z_]+)[\"']", re.MULTILINE)
_DOWN = re.compile(r"^down_revision(?:\s*:\s*[^=]+)?\s*=\s*(.+)$", re.MULTILINE)


def migration_head(versions=VERSIONS):
    """The unique head revision of the migration chain (no Alembic import)."""
    revisions, parents = set(), set()
    for path in sorted(Path(versions).glob("[0-9]*.py")):
        text = path.read_text()
        revision, down = _REVISION.search(text), _DOWN.search(text)
        if revision is None or down is None:
            raise ValueError(f"Unparseable migration: {path.name}")
        revisions.add(revision.group(1))
        parents.update(re.findall(r"[\"']([0-9A-Za-z_]+)[\"']", down.group(1)))
    heads = revisions - parents
    if len(heads) != 1:
        raise ValueError("Migration chain must have exactly one head")
    return heads.pop()


def require_consistent_schema(current=None, versions=VERSIONS):
    """Refuse fresh initialization while the backend contract lags the migration head."""
    current = CURRENT_SCHEMA if current is None else current
    head = migration_head(versions)
    if current != head:
        raise ValueError(
            f"Backend schema contract {current} lags migration head {head}; "
            "update backend/app/core/schema_version.py before initializing a deployment"
        )
    return head


__all__ = ["CURRENT_SCHEMA", "HISTORICAL_MIGRATION_CASES", "migration_head", "require_consistent_schema"]
