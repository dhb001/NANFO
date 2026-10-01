"""Explicit boundary for tests that replay the ignored private evidence store (ADR-028).

Only modules listed in private_artifacts.txt may call requirePrivateStore(). When
ai-engine/artifacts/ is absent, as in a clean CI checkout, the calling module is skipped
with an explicit reason. When the store exists, every test runs unchanged and fails
loudly if a pinned artifact is missing or differs; a partial store is never skipped.
"""

from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
STORE = TESTS.parent / "artifacts"
REGISTRY = TESTS / "private_artifacts.txt"


def registered():
    rows = REGISTRY.read_text(encoding="utf-8").splitlines()
    return {row.strip() for row in rows if row.strip() and not row.lstrip().startswith("#")}


def requirePrivateStore(module):
    name = Path(module).name
    if name not in registered():
        raise RuntimeError(f"{name} must be listed in tests/{REGISTRY.name} to read the store")
    if not STORE.is_dir():
        pytest.skip(
            f"private evidence store absent: ai-engine/artifacts/ (ADR-028, tests/{REGISTRY.name})",
            allow_module_level=True,
        )
