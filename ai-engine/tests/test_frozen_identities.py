"""ADR-028: tracked copies of the qualified runtime verify without the private store.

The copies are byte-identical to ignored evidence; nothing here re-qualifies or relabels it.
"""

import ast
import hashlib
import importlib
import importlib.util
import io
import json
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

import pytest
from conftest import SPEC_FIXTURE, SPEC_FIXTURE_SHA256, loadSpecFixture
from private_store import REGISTRY, registered

from nanfo_routing.contracts import jsonBytes

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
REPO = ROOT.parent
QUALIFIED = ROOT / "qualified/adr024-qualified-001"
CLIENT = QUALIFIED / "client-source"
CHECKPOINT = QUALIFIED / "model/checkpoint.ptz"
PARENT = QUALIFIED / "model/parent-checkpoint.ptz"
FROZEN_LAB = REPO / "emulation/frozen"
ARCHIVE = FROZEN_LAB / "adr015-prechange-v4-source.tar.gz"
# Recorded pins of the historical archive and ADR014 incumbent (scripts/recover_qualified_runtime.py
# and ai-engine/scripts/refinement/frozen.py), repeated so no historical runner is imported.
ARCHIVE_SHA256 = "444663dc3a7223044a9e8830ba5dd24cd3e1b041c60dc278e4bba56eb7252384"
PARENT_SHA256 = "5b8818af655ec8efce5d3bc3def27db599f3e0df379a0ae263dcefb5f72a80a5"
CLIENT_ALIAS = "_nanfo_adr024_qualified_client"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def labPins():
    """IMAGE/SOURCE/MODEL exactly as the experimental lab contract pins them."""
    path = REPO / "emulation/experimental_lab_contract.py"
    spec = importlib.util.spec_from_file_location("_adr028_pinned_lab_contract", path)
    module = importlib.util.module_from_spec(spec)
    saved = list(sys.path)
    sys.path[:0] = [str(REPO / "emulation"), str(REPO)]
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = saved
    return {"IMAGE": module.IMAGE, "SOURCE": module.SOURCE, "MODEL": module.MODEL}


def checksums(directory):
    rows = {}
    for line in (directory / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        assert name not in rows and PurePosixPath(name).parts[0] not in ("..", "/")
        rows[name] = digest
    return rows


def bundle(path):
    with zipfile.ZipFile(io.BytesIO(path.read_bytes())) as archive:
        assert [row.filename for row in archive.infolist()] == ["manifest.json", "weights.pt"]
        return archive.read("manifest.json"), archive.read("weights.pt")


def archiveFiles():
    content = ARCHIVE.read_bytes()
    assert sha(content) == ARCHIVE_SHA256
    files = {}
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
        for member in archive.getmembers():
            name = PurePosixPath(member.name)
            assert not name.is_absolute() and ".." not in name.parts
            assert name.parts[0] == "emulation"
            assert member.isfile() or member.isdir(), "links/devices are never admitted"
            if member.isfile():
                files[member.name] = archive.extractfile(member).read()
    return files


@pytest.mark.parametrize("directory", [QUALIFIED, FROZEN_LAB], ids=["qualified", "frozen-lab"])
def test_sha256sums_cover_every_tracked_copy_exactly(directory):
    rows = checksums(directory)
    caches = {"__pycache__", ".ruff_cache", ".pytest_cache"}  # git-ignored tool output
    present = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file()
        and path.name not in ("SHA256SUMS", "README.md")
        and not caches & set(path.parts)
    }
    assert present == set(rows)
    for name, digest in rows.items():
        assert sha((directory / name).read_bytes()) == digest, name


def test_qualified_checkpoint_matches_pinned_model_and_lineage():
    pins = labPins()
    lineage = json.loads((QUALIFIED / "model/lineage.json").read_bytes())
    manifestBytes, weights = bundle(CHECKPOINT)
    parentManifestBytes, parentWeights = bundle(PARENT)
    manifest, parent = json.loads(manifestBytes), json.loads(parentManifestBytes)
    assert sha(CHECKPOINT.read_bytes()) == pins["MODEL"] == lineage["derived_checkpoint_sha256"]
    assert sha(PARENT.read_bytes()) == PARENT_SHA256 == lineage["parent_checkpoint_sha256"]
    assert sha(manifestBytes) == lineage["derived_manifest_sha256"]
    assert sha(parentManifestBytes) == lineage["parent_manifest_sha256"]
    # Provenance rebinding only: identical tensors, only the lab image identity differs.
    assert weights == parentWeights and sha(weights) == lineage["tensor_payload_sha256"]
    assert sha(weights) == manifest["weights_sha256"]
    assert [key for key in manifest if manifest[key] != parent[key]] == ["lab_provenance"]
    assert manifest["lab_provenance"] == {
        "lab_image_id": pins["IMAGE"],
        "source_sha256": pins["SOURCE"],
    }
    assert lineage["image_id"] == pins["IMAGE"] and lineage["source_sha256"] == pins["SOURCE"]
    assert manifest["client_source_files"] == lineage["client_source_sha256"]


def test_frozen_lab_archive_rederives_pinned_source_digest():
    files = archiveFiles()
    spec = loadSpecFixture()
    derived = {name: sha(files["emulation/" + name]) for name in spec["source_files"]}
    assert derived == spec["source_files"]
    assert sha(jsonBytes(derived)) == spec["source_sha256"] == labPins()["SOURCE"]


def test_spec_fixture_is_the_qualified_checkpoint_environment_spec(tmp_path):
    manifest = json.loads(bundle(CHECKPOINT)[0])
    assert loadSpecFixture() == manifest["environment_spec"]
    assert manifest["spec_hash"] == SPEC_FIXTURE_SHA256
    drifted = json.loads(SPEC_FIXTURE.read_bytes())
    drifted["drain_max_seconds"] = 3.5
    (tmp_path / "spec.json").write_bytes(jsonBytes(drifted))
    with pytest.raises(ValueError, match="pinned spec_hash"):
        loadSpecFixture(tmp_path / "spec.json")


@pytest.fixture(scope="module")
def frozenArtifacts():
    """The unmodified frozen client, imported from its tracked copy under a distinct name."""
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location(
            CLIENT_ALIAS, CLIENT / "__init__.py", submodule_search_locations=[str(CLIENT)]
        )
        package = importlib.util.module_from_spec(spec)
        sys.modules[CLIENT_ALIAS] = package
        spec.loader.exec_module(package)
        yield importlib.import_module(CLIENT_ALIAS + ".artifacts")
    finally:
        sys.dont_write_bytecode = saved
        for name in [n for n in sys.modules if n.split(".")[0] == CLIENT_ALIAS]:
            sys.modules.pop(name)


def test_frozen_client_copy_loads_qualified_checkpoint_weights_only(frozenArtifacts, tmp_path):
    lineage = json.loads((QUALIFIED / "model/lineage.json").read_bytes())
    assert frozenArtifacts.clientSources() == lineage["client_source_sha256"]
    agent, manifest = frozenArtifacts.loadCheckpoint(CHECKPOINT)
    assert manifest.environment_spec == loadSpecFixture()
    assert manifest.lab_provenance["lab_image_id"] == labPins()["IMAGE"]
    assert agent.transitions == manifest.transitions and not agent.model.training
    tampered = bytearray(CHECKPOINT.read_bytes())
    tampered[len(tampered) // 2] ^= 1  # inside weights.pt (manifest.json is the first 9 KiB)
    (tmp_path / "tampered.ptz").write_bytes(tampered)
    with pytest.raises(ValueError):
        frozenArtifacts.loadCheckpoint(tmp_path / "tampered.ptz")


def test_private_store_guard_skips_only_when_store_is_absent(monkeypatch, tmp_path):
    import private_store

    with pytest.raises(RuntimeError, match="must be listed"):
        private_store.requirePrivateStore(TESTS / "test_frozen_identities.py")
    monkeypatch.setattr(private_store, "STORE", tmp_path / "absent")
    with pytest.raises(pytest.skip.Exception, match="private evidence store absent"):
        private_store.requirePrivateStore(TESTS / "test_refinement.py")
    (tmp_path / "partial").mkdir()
    monkeypatch.setattr(private_store, "STORE", tmp_path / "partial")
    assert private_store.requirePrivateStore(TESTS / "test_refinement.py") is None


def guardsPrivateStore(path):
    """True when the module calls requirePrivateStore(__file__) at module level."""
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        call = node.value if isinstance(node, ast.Expr) else None
        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "requirePrivateStore"
            and len(call.args) == 1
            and isinstance(call.args[0], ast.Name)
            and call.args[0].id == "__file__"
        ):
            return True
    return False


def test_private_store_registry_lists_exactly_the_guarded_modules():
    guarded = {path.name for path in TESTS.glob("test_*.py") if guardsPrivateStore(path)}
    assert guarded == registered() == {"test_refinement.py", "test_refinement_long.py"}
    for name in guarded:
        assert "pytestmark = pytest.mark.private_artifacts" in (TESTS / name).read_text()
    assert REGISTRY.name == "private_artifacts.txt"
