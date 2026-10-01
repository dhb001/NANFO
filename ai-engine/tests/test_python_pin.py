"""ADR-028 task 7: the AI interpreter is pinned exactly and consistently everywhere."""

import platform
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINNED = "3.12.14"


def test_python_version_file_pins_exact_patch_release():
    assert (ROOT / ".python-version").read_text() == PINNED + "\n"


def test_pyproject_and_lock_require_the_same_exact_interpreter():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["requires-python"] == "==" + PINNED
    lock = (ROOT / "uv.lock").read_text()
    match = re.search(r'^requires-python = "([^"]+)"$', lock, re.M)
    assert match and match.group(1) == "==" + PINNED


def test_running_interpreter_matches_the_pin():
    # `uv run --locked` must never silently execute the suite on another patch release.
    assert platform.python_version() == PINNED
