"""ADR-028 task 11: the lab package stays stdlib-only and Python 3.9 parseable."""

import ast
import unittest
from pathlib import Path

EMULATION = Path(__file__).resolve().parents[1]
# Moved implementations leave host-only compatibility shims (backend interpreter only).
HOST_ONLY = {"passive_observer.py", "native_qualification_clock.py"}
FORBIDDEN_TOP_LEVEL = {"app", "scripts", "pydantic", "sqlalchemy", "fastapi", "torch", "nanfo_routing"}
# Container-only third-party runtimes are imported lazily inside functions (or by the
# os-ken controller modules that only ever run in the lab image).
CONTAINER_MODULES = {"mininet", "os_ken"}
CONTROLLER_FILES = {"controller.py", "controller_main.py"}
PY311_NAMES = {"ExceptionGroup", "BaseExceptionGroup", "TaskGroup", "tomllib", "Self"}


def modules(tree, *, top_level_only):
    nodes = tree.body if top_level_only else ast.walk(tree)
    found = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            found |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module.split(".")[0])
    return found


class LabPackageTests(unittest.TestCase):
    def sources(self):
        return {path.name: path.read_text() for path in sorted(EMULATION.glob("*.py"))}

    def test_every_lab_module_parses_as_python39(self):
        for name, source in self.sources().items():
            if name in HOST_ONLY:
                continue
            with self.subTest(module=name):
                ast.parse(source, filename=name, feature_version=(3, 9))

    def test_lab_modules_never_import_backend_or_python311_only_features(self):
        for name, source in self.sources().items():
            if name in HOST_ONLY:
                continue
            tree = ast.parse(source)
            with self.subTest(module=name):
                self.assertFalse(modules(tree, top_level_only=False) & FORBIDDEN_TOP_LEVEL)
                if name not in CONTROLLER_FILES:
                    self.assertFalse(modules(tree, top_level_only=True) & CONTAINER_MODULES)
                used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
                used |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
                used |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                         for alias in node.names}
                self.assertFalse(used & PY311_NAMES)
                datetime_utc = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                                and node.module == "datetime" and any(a.name == "UTC" for a in node.names)]
                self.assertFalse(datetime_utc)

    def test_host_only_shims_contain_no_implementation(self):
        for name in HOST_ONLY:
            tree = ast.parse((EMULATION / name).read_text())
            with self.subTest(module=name):
                self.assertFalse([node for node in tree.body
                                  if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))])
                self.assertIn("app.modules.autonomy.experimental.", (EMULATION / name).read_text())


if __name__ == "__main__":
    unittest.main()
