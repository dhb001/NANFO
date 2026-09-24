"""Bounded real rendering and protected, descriptor-relative filesystem storage."""

import csv
import hashlib
import io
import json
import os
import stat
import textwrap
import threading
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from app.core.canonical import canonical_json_bytes, canonical_sha256
from app.core.logging import get_logger

logger = get_logger(__name__)


class ReportCapacityError(OSError):
    """Protected report storage cannot accommodate another bounded artifact."""


def canonical(value):
    """Strict canonical JSON bytes of report snapshots/receipts.

    ADR-028: delegates to ``app.core.canonical``, proven byte-identical to the
    historical local encoder (sorted keys, compact separators, ASCII, no NaN), so
    every recorded ``snapshot_sha256``/``receipt_sha256`` remains valid.
    """
    return canonical_json_bytes(value)


def digest(value):
    return canonical_sha256(value)


# ADR-028: an embedded Unicode TrueType monospace font (see fonts/README.md).
FONT_FILE = Path(__file__).resolve().parent / "fonts" / "DejaVuSansMono.ttf"
FONT_SHA256 = "b4a6c3e4faab8773f4ff761d56451646409f29abedd68f05d38c2df667d3c582"
FONT_NAME = "NANFO-DejaVuSansMono"
PDF_FONT_SIZE = 8
PDF_WRAP_COLUMNS = 108
PDF_NOTICE = (
    "NANFO scoped snapshot. Embedded DejaVu Sans Mono; characters it cannot show, right-to-left "
    "and control characters use reversible JSON \\uXXXX escapes; no text cropped."
)
# Fallback: ReportLab's bundled standard Courier (metrics ship with ReportLab; the
# pre-ADR-028 renderer). Printable ASCII only, so everything else stays escaped.
FALLBACK_FONT_NAME = "Courier"
FALLBACK_PDF_NOTICE = (
    "NANFO scoped snapshot. Standard Courier (embedded Unicode font unavailable); non-ASCII "
    "and control characters use reversible JSON \\uXXXX escapes; no text cropped."
)
_ESCAPED_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})
_RIGHT_TO_LEFT = frozenset({"R", "AL", "AN"})
_font_lock = threading.Lock()
_pdf_font: "PdfFont | None" = None


@dataclass(frozen=True)
class PdfFont:
    """The PDF font in use: ``glyphs`` are the non-ASCII code points shown as text."""

    name: str
    glyphs: frozenset[int]
    notice: str
    embedded: bool


def _load_embedded_font() -> PdfFont:
    data = FONT_FILE.read_bytes()
    if hashlib.sha256(data).hexdigest() != FONT_SHA256:
        raise ValueError("Embedded report font failed integrity verification")
    font = TTFont(FONT_NAME, io.BytesIO(data))
    # Wrapping by character count is exact only for a single advance width.
    if len(set(font.face.charWidths.values())) != 1:
        raise ValueError("Embedded report font must be monospaced")
    pdfmetrics.registerFont(font)
    return PdfFont(FONT_NAME, frozenset(font.face.charToGlyph), PDF_NOTICE, True)


def pdf_font() -> PdfFont:
    """Verified embedded Unicode font, else ReportLab's bundled standard Courier.

    Unverified bytes are never embedded: a missing, unreadable, altered (SHA-256
    mismatch) or non-monospaced font file selects the fallback once per process
    (logged), which shows printable ASCII only -- every other character keeps its
    reversible escape, exactly as before ADR-028.
    """
    global _pdf_font
    with _font_lock:
        if _pdf_font is None:
            try:
                _pdf_font = _load_embedded_font()
            except Exception as exc:  # noqa: BLE001 - any font fault selects the bundled fallback
                logger.warning("report_pdf_font_fallback", font=FALLBACK_FONT_NAME, error_type=type(exc).__name__)
                _pdf_font = PdfFont(FALLBACK_FONT_NAME, frozenset(), FALLBACK_PDF_NOTICE, False)
        return _pdf_font


def pdf_font_glyphs() -> frozenset[int]:
    """Non-ASCII code points the selected PDF font shows as text."""
    return pdf_font().glyphs


def _json_escape(char):
    code = ord(char)
    if code > 0xFFFF:
        code -= 0x10000
        return "\\u%04x\\u%04x" % (0xD800 + (code >> 10), 0xDC00 + (code & 0x3FF))
    return "\\u%04x" % code


def pdf_text(text, glyphs):
    """Show covered characters as text; reversible JSON escapes for all others.

    Callers pass JSON text (values) or JSON string bodies (sections/paths), whose
    backslashes are already escaped, so every PDF cell decodes back to its value.
    """
    shown = []
    for char in text:
        code = ord(char)
        if 0x20 <= code < 0x7F or (
            code in glyphs
            and unicodedata.category(char) not in _ESCAPED_CATEGORIES
            and unicodedata.bidirectional(char) not in _RIGHT_TO_LEFT
        ):
            shown.append(char)
        else:
            shown.append(_json_escape(char))
    return "".join(shown)


def _cells(snapshot):
    # Flatten to lossless JSON-pointer paths/cells, not clipped tables.
    cells = []

    def flatten(section, index, path, value):
        if isinstance(value, dict) and value:
            for key, child in sorted(value.items()):
                flatten(
                    section,
                    index,
                    path + "/" + key.replace("~", "~0").replace("/", "~1"),
                    child,
                )
        elif isinstance(value, list) and value:
            for i, child in enumerate(value):
                flatten(section, index, path + "/" + str(i), child)
        else:
            cells.append((section, str(index), path, value))

    flatten(
        "metadata",
        "",
        "",
        {key: value for key, value in snapshot.items() if key != "sections"},
    )
    for section, contents in snapshot["sections"].items():
        flatten(
            section,
            "",
            "/summary",
            {key: value for key, value in contents.items() if key != "rows"},
        )
        for index, row in enumerate(contents["rows"]):
            flatten(section, index, "", row)
    return cells


HEADER = ("section", "row", "field", "value")


def render(snapshot, output_format, max_bytes):
    cells = _cells(snapshot)
    if len(cells) + 1 > 30000:
        raise ValueError("Report exceeds cell limit; narrow scope")
    if output_format == "csv":
        # CSV keeps lossless ASCII JSON values (non-ASCII as reversible escapes).
        rows = [HEADER, *(
            (section, index, path, json.dumps(value, ensure_ascii=True, allow_nan=False))
            for section, index, path, value in cells
        )]
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        for row in rows:
            # Apply to every cell, including field names and leading control/space.
            writer.writerow(
                [
                    "'" + cell
                    if cell.lstrip(" \t\r\n").startswith(("=", "+", "-", "@"))
                    or cell.startswith(("\t", "\r", "\n"))
                    else cell
                    for cell in row
                ]
            )
        data = output.getvalue().encode("utf-8")
    elif output_format == "pdf":
        font = pdf_font()
        glyphs = font.glyphs

        def body(text):
            return pdf_text(json.dumps(text, ensure_ascii=False)[1:-1], glyphs)

        lines = [font.notice, " | ".join(HEADER), *(
            " | ".join((body(section), body(index), body(path),
                        pdf_text(json.dumps(value, ensure_ascii=False, allow_nan=False), glyphs)))
            for section, index, path, value in cells
        )]
        output = io.BytesIO()
        pdf = canvas.Canvas(output, pagesize=(612, 792), pageCompression=1, invariant=1)
        pdf.setTitle("NANFO scoped report")
        y, pages = 754, 1
        pdf.setFont(font.name, PDF_FONT_SIZE)
        for line in lines:
            for part in textwrap.wrap(
                line,
                width=PDF_WRAP_COLUMNS,
                replace_whitespace=False,
                drop_whitespace=False,
            ) or [""]:
                if y < 38:
                    pdf.showPage()
                    pages += 1
                    if pages > 600:
                        raise ValueError("Report exceeds PDF page limit; narrow scope")
                    pdf.setFont(font.name, PDF_FONT_SIZE)
                    y = 754
                pdf.drawString(36, y, part)
                y -= 10
        pdf.save()
        data = output.getvalue()
    else:
        raise ValueError("Unsupported format")
    if not 0 < len(data) <= max_bytes:
        raise ValueError("Report exceeds byte limit; narrow scope")
    return data


class VerifiedArtifact:
    """An open, already verified artifact inode streamed by offset, never by path.

    ``chunks`` re-hashes while streaming and withholds the final block when the
    bytes changed after verification, so an altered file never completes a
    download. ``close`` is idempotent and safe from another thread.
    """

    def __init__(self, fd, size, checksum_sha256, chunk_size=65536):
        self._fd, self.size, self.checksum_sha256 = fd, size, checksum_sha256
        self._chunk_size = chunk_size
        self._lock = threading.Lock()

    def _read(self, length, offset):
        with self._lock:
            if self._fd is None:
                raise ValueError("Artifact stream closed")
            return os.pread(self._fd, length, offset)

    def chunks(self):
        hasher, offset = hashlib.sha256(), 0
        try:
            while offset < self.size:
                block = self._read(min(self._chunk_size, self.size - offset), offset)
                if not block:
                    raise ValueError("Artifact truncated while streaming")
                hasher.update(block)
                offset += len(block)
                if offset == self.size and (
                    self._read(1, offset) or hasher.hexdigest() != self.checksum_sha256
                ):
                    raise ValueError("Artifact changed after verification")
                yield block
        finally:
            self.close()

    def close(self):
        with self._lock:
            fd, self._fd = self._fd, None
        if fd is not None:
            os.close(fd)


class ArtifactStore:
    def __init__(self, root, max_bytes):
        self.root, self.max_bytes = Path(root), max_bytes

    def capacity(self, min_free_bytes):
        directory = self._directory()
        try:
            info = os.fstatvfs(directory)
            available = info.f_bavail * info.f_frsize
            return {
                "available_bytes": available,
                "min_free_bytes": min_free_bytes,
                "required_bytes": min_free_bytes + self.max_bytes,
                "ready": available >= min_free_bytes + self.max_bytes
                and info.f_favail > 0,
            }
        finally:
            os.close(directory)

    def require_capacity(self, min_free_bytes):
        if not self.capacity(min_free_bytes)["ready"]:
            raise ReportCapacityError("Report storage reserve exhausted")

    def _directory(self):
        source = Path(__file__).resolve().parents[4]
        if (
            not self.root.is_absolute()
            or ".." in self.root.parts
            or self.root.is_relative_to(source)
        ):
            raise ValueError("Storage must be absolute and outside the source tree")
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in self.root.parts[1:]:
                next_fd = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
                )
                os.close(fd)
                fd = next_fd
            info = os.fstat(fd)
            if info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise ValueError("Storage must be owned by backend UID with mode 0700")
            return fd
        except BaseException:
            os.close(fd)
            raise

    @staticmethod
    def filename(report_id, artifact_id, output_format):
        if output_format not in {"pdf", "csv"}:
            raise ValueError("Invalid artifact format")
        return (
            f"{uuid.UUID(str(report_id))}-{uuid.UUID(str(artifact_id))}.{output_format}"
        )

    def write(
        self, report_id, artifact_id, output_format, data, *, min_free_bytes=67108864
    ):
        if not 0 < len(data) <= self.max_bytes:
            raise ValueError("Artifact size invalid")
        self.require_capacity(min_free_bytes)
        name = self.filename(report_id, artifact_id, output_format)
        directory = self._directory()
        temp = "." + uuid.uuid4().hex + ".tmp"
        try:
            fd = os.open(
                temp,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory,
            )
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            # Refuse preexisting identities, including symlinks. Leases have unique IDs.
            try:
                os.stat(name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                os.rename(temp, name, src_dir_fd=directory, dst_dir_fd=directory)
            else:
                raise FileExistsError("Artifact identity already exists")
            os.fsync(directory)
        finally:
            try:
                os.unlink(temp, dir_fd=directory)
            except FileNotFoundError:
                pass
            os.close(directory)
        return {
            "artifact_id": str(artifact_id),
            "checksum_sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
            "filename": name,
            "media_type": "application/pdf" if output_format == "pdf" else "text/csv",
        }

    def _receipt_name(self, report_id, output_format, receipt):
        name = self.filename(report_id, receipt["artifact_id"], output_format)
        if (
            receipt["filename"] != name
            or not 0 < receipt["size_bytes"] <= self.max_bytes
        ):
            raise ValueError("Invalid receipt")
        return name

    def _open_checked(self, name, receipt):
        directory = self._directory()
        try:
            fd = os.open(
                name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
            )
        finally:
            os.close(directory)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or info.st_mode & 0o077
                or info.st_nlink != 1
            ):
                raise ValueError("Unsafe artifact")
            if info.st_size != receipt["size_bytes"]:
                raise ValueError("Artifact size mismatch")
            return fd
        except BaseException:
            os.close(fd)
            raise

    def read(self, report_id, output_format, receipt):
        name = self._receipt_name(report_id, output_format, receipt)
        fd = self._open_checked(name, receipt)
        with os.fdopen(fd, "rb") as stream:
            data = stream.read(self.max_bytes + 1)
        if (
            len(data) != receipt["size_bytes"]
            or hashlib.sha256(data).hexdigest() != receipt["checksum_sha256"]
        ):
            raise ValueError("Artifact checksum mismatch")
        # Verified immutable bytes, not a path that can change after validation.
        return data

    def open_verified(self, report_id, output_format, receipt, *, chunk_size=65536):
        """Verify length/SHA-256 in bounded chunks, then return the open inode.

        Downloads stream this verified descriptor (never the path again), so
        memory stays O(chunk) instead of holding the whole artifact.
        """
        name = self._receipt_name(report_id, output_format, receipt)
        fd = self._open_checked(name, receipt)
        try:
            size, hasher, offset = receipt["size_bytes"], hashlib.sha256(), 0
            while offset < size:
                block = os.pread(fd, min(chunk_size, size - offset), offset)
                if not block:
                    raise ValueError("Artifact size mismatch")
                hasher.update(block)
                offset += len(block)
            if os.pread(fd, 1, offset) or hasher.hexdigest() != receipt["checksum_sha256"]:
                raise ValueError("Artifact checksum mismatch")
            return VerifiedArtifact(fd, size, receipt["checksum_sha256"], chunk_size)
        except BaseException:
            os.close(fd)
            raise

    def remove(self, report_id, output_format, receipt):
        """Unlink one attempt file named by its receipt; never follows symlinks.

        Used for attempts whose terminal CAS lost (the row never references them)
        and for retention of expired reports. Returns False when already absent.
        """
        name = self.filename(report_id, receipt["artifact_id"], output_format)
        if receipt.get("filename", name) != name:
            raise ValueError("Invalid receipt")
        directory = self._directory()
        try:
            try:
                info = os.stat(name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                return False
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
                raise ValueError("Refusing to remove an unsafe artifact")
            os.unlink(name, dir_fd=directory)
            os.fsync(directory)
            return True
        finally:
            os.close(directory)


def valid_receipt(record, *, verify_snapshot=True):
    """Receipt integrity; ``verify_snapshot`` re-hashes the frozen snapshot.

    Detail/download/replay verify the snapshot hash (callers run it off the event
    loop). History pages use ``verify_snapshot=False``: the receipt is still bound
    to the recorded ``snapshot_sha256`` and its own digest, without loading or
    hashing up to 1 MiB of snapshot per row.
    """
    receipt = getattr(record, "receipt", None)
    if getattr(record, "artifact_version", 0) != 1 or not isinstance(receipt, dict):
        return False
    try:
        return (
            record.status == "generated"
            and record.status_version >= 2
            and receipt["snapshot_sha256"] == record.snapshot_sha256
            and (not verify_snapshot or record.snapshot_sha256 == digest(record.snapshot))
            and receipt["status_version"] == record.status_version
            and receipt["receipt_sha256"]
            == digest(
                {
                    key: value
                    for key, value in receipt.items()
                    if key != "receipt_sha256"
                }
            )
            and receipt["filename"]
            == ArtifactStore.filename(
                record.report_id, receipt["artifact_id"], record.output_format
            )
            and receipt["media_type"]
            == ("application/pdf" if record.output_format == "pdf" else "text/csv")
            and len(receipt["checksum_sha256"]) == 64
            and receipt["size_bytes"] > 0
        )
    except (KeyError, TypeError, ValueError):
        return False
