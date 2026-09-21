import csv
import hashlib
import io
import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.modules.report.artifacts import ArtifactStore, digest, render, valid_receipt
from tests.report_support import snapshot


def test_real_csv_cells_formula_and_unicode_lossless():
    value = snapshot()
    value["sections"]["=malicious"] = {
        "rows": [{"=field": "\u00e9\u4e2d<>&"}],
        "total": 1,
    }
    rows = list(csv.reader(io.StringIO(render(value, "csv", 100000).decode())))
    assert rows[0] == ["section", "row", "field", "value"]
    assert any(row[3] == "12.5" for row in rows)
    assert any(row[0] == "'=malicious" and "\\u4e2d" in row[3] for row in rows)
    assert all(
        not cell.lstrip().startswith(("=", "+", "-", "@"))
        for row in rows
        for cell in row
    )


def test_real_pdf_parsed_text_wraps_not_cropped():
    pypdf = pytest.importorskip(
        "pypdf", reason="Install backend dev dependencies to parse PDFs"
    )
    value = snapshot()
    value["sections"]["telemetry"]["rows"].append(
        {"long": "x" * 2000 + "VISIBLE_END", "unicode": "\u00e9\u4e2d"}
    )
    data = render(value, "pdf", 100000)
    assert data.startswith(b"%PDF-")
    document = pypdf.PdfReader(io.BytesIO(data))
    text = "".join(page.extract_text() for page in document.pages)
    assert "12.5" in text and "VISIBLE_END" in text and "\\u4e2d" in text
    assert "Unicode uses reversible JSON escapes" in text


@pytest.mark.parametrize("fmt", ["csv", "pdf"])
def test_render_byte_cap(fmt):
    with pytest.raises(ValueError):
        render(snapshot(), fmt, 10)


def test_store_actual_bytes_tamper_length_symlink_and_permissions(tmp_path):
    os.chmod(tmp_path, 0o700)
    store = ArtifactStore(tmp_path, 10000)
    report, artifact = uuid.uuid4(), uuid.uuid4()
    receipt = store.write(report, artifact, "csv", b"actual,bytes\r\n")
    assert receipt["checksum_sha256"] == hashlib.sha256(b"actual,bytes\r\n").hexdigest()
    assert store.read(report, "csv", receipt) == b"actual,bytes\r\n"
    target = tmp_path / receipt["filename"]
    target.write_bytes(b"tamper,bytes\r\n")
    with pytest.raises(ValueError):
        store.read(report, "csv", receipt)
    target.write_bytes(b"short")
    with pytest.raises(ValueError):
        store.read(report, "csv", receipt)
    target.unlink()
    target.symlink_to("/etc/passwd")
    with pytest.raises(OSError):
        store.read(report, "csv", receipt)
    with pytest.raises(OSError):
        store.write(report, artifact, "csv", b"new")
    assert target.is_symlink()


def test_store_rejects_non_private_root_and_parent_symlinks(tmp_path):
    os.chmod(tmp_path, 0o755)
    with pytest.raises(ValueError):
        ArtifactStore(tmp_path, 1000).write(uuid.uuid4(), uuid.uuid4(), "csv", b"a")
    os.chmod(tmp_path, 0o700)
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(OSError):
        ArtifactStore(link, 1000).write(uuid.uuid4(), uuid.uuid4(), "csv", b"a")


@pytest.mark.parametrize(
    "path", ["relative/path", "/tmp/../tmp", str(Path(__file__).resolve().parents[2])]
)
def test_storage_outside_source_absolute_no_traversal(path):
    with pytest.raises(ValueError):
        ArtifactStore(path, 1000).write(uuid.uuid4(), uuid.uuid4(), "csv", b"a")


def test_filenames_never_accept_client_path():
    with pytest.raises(ValueError):
        ArtifactStore.filename("../../etc/passwd", uuid.uuid4(), "csv")


def test_receipt_binds_snapshot_version_identity_and_metadata(tmp_path):
    value = snapshot()
    report_id, artifact_id = uuid.uuid4(), uuid.uuid4()
    receipt = ArtifactStore(tmp_path, 100000).write(
        report_id, artifact_id, "csv", render(value, "csv", 100000)
    )
    receipt.update(
        snapshot_sha256=digest(value),
        status_version=3,
        generated_at="2026-08-02T00:00:00Z",
    )
    receipt["receipt_sha256"] = digest(receipt)
    row = SimpleNamespace(
        report_id=report_id,
        output_format="csv",
        status="generated",
        status_version=3,
        artifact_version=1,
        snapshot=value,
        snapshot_sha256=digest(value),
        receipt=receipt,
    )
    assert valid_receipt(row)
    for key, bad in (
        ("artifact_version", 0),
        ("status_version", 4),
        ("report_id", uuid.uuid4()),
        ("snapshot", {}),
    ):
        previous = getattr(row, key)
        setattr(row, key, bad)
        assert not valid_receipt(row)
        setattr(row, key, previous)
    receipt["size_bytes"] += 1
    assert not valid_receipt(row)
