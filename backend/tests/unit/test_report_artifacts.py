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
    assert "12.5" in text and "VISIBLE_END" in text
    # ADR-028 (intentional change): covered characters render as text through the
    # embedded Unicode font; uncovered CJK keeps a reversible JSON escape.
    assert "\u00e9\\u4e2d" in text and "\\u00e9" not in text
    assert "reversible JSON \\uXXXX escapes" in text


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


# ---------------------------------------------------------------- ADR-028 ---

GOLDEN_SNAPSHOT = {
    "version": 1,
    "request": {"workspace_id": "00000000-0000-0000-0000-00000000001b", "report_type": "alerts"},
    "capture_started_at": "2026-09-01T00:00:00+00:00",
    "sections": {
        "alerts": {
            "rows": [
                {"name": "R\u00e9seau \u0416\u0443\u043a \u03a9", "cjk": "\u4e2d\u6587", "rtl": "\u05e9\u05dc\u05d5\u05dd",
                 "formula": "=SUM(A1)", "neg": -1.5, "nested": {"a/b": [1, 2.25, None, True]}, "emoji": "\U0001F600",
                 "ctrl": "tab\there\u007f", "empty": {}, "list": []},
            ],
            "total": 1, "truncated": False, "omissions": ["arbitrary_payload"], "time_field": "created_at",
        },
        "=weird~/section": {"rows": [{"@key": "+1"}], "total": 1},
    },
}
# SHA-256 of the CSV produced by the pre-ADR-028 renderer for GOLDEN_SNAPSHOT.
GOLDEN_CSV_SHA256 = "4c0e94566bf31b095bb8c1363d57171cd9c80d0b7dd1941ff90fa9c6f07fa496"


def historical_canonical(value):
    """The report module's pre-ADR-028 local encoder, kept verbatim for proof."""
    import json

    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode()


@pytest.mark.parametrize("value", [
    GOLDEN_SNAPSHOT,
    snapshot(),
    {"b": 1, "a": [1.0, -0.0, 1e-7, 1e21, 10**30, -(2**63)], "c": {"\u00e9": "\u4e2d\U0001F600"}},
    ["", None, True, False, {}, []],
    "\u2028\u0000\"\\",
])
def test_canonical_digest_is_byte_identical_to_the_historical_encoder(value):
    from app.core.canonical import canonical_json_bytes, canonical_sha256
    from app.modules.report.artifacts import canonical

    assert canonical(value) == canonical_json_bytes(value) == historical_canonical(value)
    assert digest(value) == canonical_sha256(value) == hashlib.sha256(historical_canonical(value)).hexdigest()


def test_canonical_digest_still_rejects_non_finite_numbers():
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValueError):
            digest({"value": bad})
        with pytest.raises(ValueError):
            historical_canonical({"value": bad})


def test_csv_bytes_are_unchanged_by_the_unicode_pdf_font():
    data = render(GOLDEN_SNAPSHOT, "csv", 100000)
    assert hashlib.sha256(data).hexdigest() == GOLDEN_CSV_SHA256
    assert "\\u00e9".encode() in data and "\u00e9".encode() not in data


def test_pdf_embeds_verified_unicode_truetype_font_deterministically():
    pypdf = pytest.importorskip("pypdf", reason="Install backend dev dependencies to parse PDFs")
    first, second = render(GOLDEN_SNAPSHOT, "pdf", 200000), render(GOLDEN_SNAPSHOT, "pdf", 200000)
    assert first == second  # invariant output: stable artifact checksums
    assert b"/FontFile2" in first and b"DejaVuSansMono" in first and b"/Courier" not in first
    text = "".join(page.extract_text() for page in pypdf.PdfReader(io.BytesIO(first)).pages)
    assert "R\u00e9seau \u0416\u0443\u043a \u03a9" in text  # Latin/Cyrillic/Greek names as text
    assert "\\u4e2d\\u6587" in text  # not in the font: reversible escape
    assert "\\u05e9\\u05dc\\u05d5\\u05dd" in text  # right-to-left: escape, never reversed glyphs
    assert "\\ud83d\\ude00" in text  # astral: JSON surrogate-pair escape
    assert "tab\\there\\u007f" in text  # controls stay escaped


def test_pdf_cell_text_decodes_back_to_the_original_value():
    import json

    from app.modules.report.artifacts import pdf_font_glyphs, pdf_text

    glyphs = pdf_font_glyphs()
    for value in ["R\u00e9seau", "\u4e2d", "\u05e9", "\U0001F600", "a\\u4e2d", "\u202egnp.exe", "\u00a0\u200b"]:
        shown = pdf_text(json.dumps(value, ensure_ascii=False), glyphs)
        assert json.loads(shown) == value
    assert pdf_text('"\u202e"', glyphs) == '"\\u202e"'  # bidi override is never rendered


def _unusable_font(fault, monkeypatch, tmp_path):
    import app.modules.report.artifacts as artifacts

    if fault == "tampered":
        path = tmp_path / "DejaVuSansMono.ttf"
        data = bytearray(artifacts.FONT_FILE.read_bytes())
        data[len(data) // 2] ^= 0xFF  # one flipped byte in the glyph data
        path.write_bytes(bytes(data))
    elif fault == "missing":
        path = tmp_path / "absent.ttf"
    else:  # verified bytes of a proportional font: wrapping by column count would not be exact
        import reportlab

        path = Path(reportlab.__file__).parent / "fonts" / "Vera.ttf"
        monkeypatch.setattr(artifacts, "FONT_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    monkeypatch.setattr(artifacts, "FONT_FILE", path)
    monkeypatch.setattr(artifacts, "_pdf_font", None)  # restored after the test
    return artifacts


@pytest.mark.parametrize("fault", ["tampered", "missing", "proportional"])
def test_unusable_font_falls_back_to_bundled_courier_and_never_embeds_it(monkeypatch, tmp_path, fault):
    """ADR-028 (intentional change): fall back to ReportLab's bundled Courier, never fail or embed unverified bytes."""
    pypdf = pytest.importorskip("pypdf", reason="Install backend dev dependencies to parse PDFs")
    artifacts = _unusable_font(fault, monkeypatch, tmp_path)
    warnings = []
    monkeypatch.setattr(artifacts.logger, "warning", lambda event, **fields: warnings.append((event, fields)))
    first, second = render(GOLDEN_SNAPSHOT, "pdf", 200000), render(GOLDEN_SNAPSHOT, "pdf", 200000)
    assert first == second and first.startswith(b"%PDF-")
    assert b"/Courier" in first and b"/FontFile2" not in first and b"DejaVu" not in first and b"Vera" not in first
    text = "".join(page.extract_text() for page in pypdf.PdfReader(io.BytesIO(first)).pages)
    assert "Standard Courier (embedded Unicode font unavailable)" in text
    # Printable ASCII only: every other character keeps its reversible JSON escape.
    assert "R\\u00e9seau \\u0416\\u0443\\u043a \\u03a9" in text and "\u00e9" not in text
    assert "\\ud83d\\ude00" in text and "tab\\there\\u007f" in text
    font = artifacts.pdf_font()
    assert font.name == "Courier" and not font.embedded and font.glyphs == frozenset()
    assert [event for event, _ in warnings] == ["report_pdf_font_fallback"]  # once per process
    assert hashlib.sha256(render(GOLDEN_SNAPSHOT, "csv", 100000)).hexdigest() == GOLDEN_CSV_SHA256


def test_fallback_cells_still_decode_back_to_the_original_value():
    import json

    from app.modules.report.artifacts import pdf_text

    for value in ["R\u00e9seau", "\u4e2d", "\U0001F600", "a\\u4e2d", "tab\there\u007f", "\u202egnp.exe"]:
        shown = pdf_text(json.dumps(value, ensure_ascii=False), frozenset())
        assert shown.isascii() and json.loads(shown) == value


def test_font_provenance_record_matches_the_embedded_files():
    from app.modules.report.artifacts import FONT_FILE, FONT_SHA256

    readme = (FONT_FILE.parent / "README.md").read_text()
    assert hashlib.sha256(FONT_FILE.read_bytes()).hexdigest() == FONT_SHA256
    assert FONT_SHA256 in readme
    license_digest = hashlib.sha256((FONT_FILE.parent / "LICENSE").read_bytes()).hexdigest()
    assert license_digest in readme


def test_verified_artifact_streams_by_descriptor_and_withholds_changed_bytes(tmp_path):
    os.chmod(tmp_path, 0o700)
    store = ArtifactStore(tmp_path, 10000)
    report, artifact = uuid.uuid4(), uuid.uuid4()
    body = b"0123456789" * 50
    receipt = store.write(report, artifact, "csv", body, min_free_bytes=0)
    stream = store.open_verified(report, "csv", receipt, chunk_size=64)
    assert b"".join(stream.chunks()) == body
    stream.close()  # idempotent
    # Modified after verification (same size): the final block is never sent.
    stream = store.open_verified(report, "csv", receipt, chunk_size=64)
    (tmp_path / receipt["filename"]).write_bytes(body[:-1] + b"X")
    sent = []
    with pytest.raises(ValueError, match="changed"):
        for block in stream.chunks():
            sent.append(block)
    assert len(b"".join(sent)) < len(body)
    with pytest.raises(ValueError):
        store.open_verified(report, "csv", receipt)


def test_remove_unlinks_only_the_named_regular_attempt_file(tmp_path):
    os.chmod(tmp_path, 0o700)
    store = ArtifactStore(tmp_path, 10000)
    report, artifact = uuid.uuid4(), uuid.uuid4()
    receipt = store.write(report, artifact, "csv", b"a,b\r\n", min_free_bytes=0)
    assert store.remove(report, "csv", receipt) is True
    assert not (tmp_path / receipt["filename"]).exists()
    assert store.remove(report, "csv", receipt) is False
    (tmp_path / receipt["filename"]).symlink_to(tmp_path / "elsewhere")
    with pytest.raises(ValueError):
        store.remove(report, "csv", receipt)
    with pytest.raises(ValueError):
        store.remove(report, "csv", {**receipt, "filename": "../escape.csv"})


def test_history_receipt_check_binds_snapshot_hash_without_hashing_the_snapshot(tmp_path):
    value = snapshot()
    report_id, artifact_id = uuid.uuid4(), uuid.uuid4()
    receipt = ArtifactStore(tmp_path, 100000).write(report_id, artifact_id, "csv", render(value, "csv", 100000),
                                                    min_free_bytes=0)
    receipt.update(snapshot_sha256=digest(value), status_version=3, generated_at="2026-08-02T00:00:00Z")
    receipt["receipt_sha256"] = digest(receipt)
    summary_row = SimpleNamespace(report_id=report_id, output_format="csv", status="generated", status_version=3,
                                  artifact_version=1, snapshot_sha256=digest(value), receipt=receipt)
    assert not hasattr(summary_row, "snapshot")
    assert valid_receipt(summary_row, verify_snapshot=False)
    summary_row.snapshot_sha256 = "0" * 64
    assert not valid_receipt(summary_row, verify_snapshot=False)
