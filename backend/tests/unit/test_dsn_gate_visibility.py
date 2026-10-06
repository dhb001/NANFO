"""DSN-gated suites must name their gate in their own source (ADR-028).

The database-contracts drift guard (.github/workflows/disposable-integration.yml)
finds DSN-gated suites by searching each test file's text for a ``*_TEST_DSN`` /
``*_TEST_REDIS_URL`` name. A module that re-uses another module's ``pytestmark``
is skipped by that gate but is invisible to the guard, so no CI lane executes it.
"""

import ast
import re
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]
BACKEND = TESTS.parent
DSN = re.compile(r"\b[A-Z][A-Z0-9_]*_TEST_(?:DSN|REDIS_URL)\b")


def inherited_gate_sources(source: str) -> set[str]:
    """Dotted ``tests.*`` modules whose module-level ``pytestmark`` this module re-uses."""
    tree = ast.parse(source)
    aliases, sources = {}, set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").startswith("tests."):
            for alias in node.names:
                if alias.name == "pytestmark":
                    sources.add(node.module)
                else:
                    aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("tests.") and alias.asname:
                    aliases[alias.asname] = alias.name
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if not any(isinstance(target, ast.Name) and target.id == "pytestmark" for target in targets):
            continue
        for sub in ast.walk(value):
            if isinstance(sub, ast.Attribute) and sub.attr == "pytestmark":
                owner = ast.unparse(sub.value)
                if owner in aliases:
                    sources.add(aliases[owner])
                elif owner.startswith("tests."):
                    sources.add(owner)
    return sources


def test_scanner_finds_attribute_and_import_reuse_of_another_modules_pytestmark():
    assert inherited_gate_sources(
        "from tests.integration import test_retention_complete_postgres as support\n"
        "pytestmark = support.pytestmark\n"
    ) == {"tests.integration.test_retention_complete_postgres"}
    assert inherited_gate_sources(
        "import tests.integration.test_alert_postgres as alerts\n"
        "from tests.integration.test_report_postgres import pytestmark as report_gate\n"
        "pytestmark = [alerts.pytestmark, report_gate]\n"
    ) == {"tests.integration.test_alert_postgres", "tests.integration.test_report_postgres"}
    assert inherited_gate_sources(
        "import pytest\n"
        "from tests.integration.test_retention_complete_postgres import metric\n"
        "pytestmark = pytest.mark.skipif(True, reason='own gate')\n"
    ) == set()


def test_every_suite_reusing_a_dsn_gate_names_that_dsn_for_the_drift_guard():
    hidden = []
    for path in sorted(TESTS.rglob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        own = set(DSN.findall(text))
        for dotted in sorted(inherited_gate_sources(text)):
            gate_file = BACKEND / (dotted.replace(".", "/") + ".py")
            gate = set(DSN.findall(gate_file.read_text(encoding="utf-8")))
            if gate and not gate & own:
                hidden.append(f"{path.relative_to(BACKEND)} re-uses the {sorted(gate)} gate of {dotted}")
    assert hidden == []
