"""Read-only imports of the completed, hash-bound ADR015 implementation."""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
PREVIOUS = ROOT / "artifacts/adr015-002"
PARENT_HASH = "50437cbc01c9ed029f40875943fbfe6d6c89f0fe7ccebf90a5a3e71e6780d75f"
IMAGE = "sha256:31c749ef79621fc15e959991f04ab5884f2cb3a16924ad3fc522f74edd3f48d9"


def digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def loadHistory():
    plan = json.loads((PREVIOUS / "plan.json").read_bytes())
    modules, preceding = {}, {}
    # Old scripts have absolute sibling imports. Bind them only during import,
    # restore the caller namespace afterward; do not patch their function globals.
    try:
        for name in ("frozen", "plan", "evidence", "audit", "model", "campaign"):
            path = ROOT / "scripts/refinement" / (name + ".py")
            if digest(path) != plan["refinement_sources"][path.name]:
                raise ValueError("completed ADR015 source changed")
            alias = "_adr016_history_" + name
            spec = importlib.util.spec_from_file_location(alias, path)
            mod = importlib.util.module_from_spec(spec)
            preceding[name] = sys.modules.get(name)
            sys.modules[alias] = sys.modules[name] = mod
            spec.loader.exec_module(mod)
            modules[name] = mod
    finally:
        for name, mod in preceding.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod
    return modules


OLD = loadHistory()
c = OLD["frozen"].module("contracts")
a = OLD["frozen"].module("artifacts")
ppo = OLD["frozen"].module("ppo")
env = OLD["frozen"].module("env")
read = OLD["campaign"].read
write = OLD["campaign"].write
INCUMBENT_HASH = OLD["frozen"].PARENT_HASH


def parent():
    plan = read(PREVIOUS / "plan.json")
    plan["plan_sha256"] = digest(PREVIOUS / "plan.json")
    path = PREVIOUS / "candidate-512.ptz"
    agent, metadata = OLD["model"].load(path, PARENT_HASH, plan)
    if metadata["transitions"] != 512 or metadata["updates"] != 32:
        raise ValueError("parent is not completed candidate512")
    return agent, metadata
