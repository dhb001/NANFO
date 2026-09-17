"""Bounded real rendering and protected, descriptor-relative filesystem storage."""

import csv
import hashlib
import io
import json
import os
import stat
import textwrap
import uuid
from pathlib import Path

from reportlab.pdfgen import canvas


class ReportCapacityError(OSError):
    """Protected report storage cannot accommodate another bounded artifact."""


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def render(snapshot, output_format, max_bytes):
    # Flatten to lossless JSON paths/cells, not clipped tables. Unicode is represented
    # by reversible JSON escapes because the default PDF font has no Unicode coverage.
    rows = [("section", "row", "field", "value")]

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
            rows.append(
                (
                    section,
                    str(index),
                    path,
                    json.dumps(value, ensure_ascii=True, allow_nan=False),
                )
            )

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
    if len(rows) > 30000:
        raise ValueError("Report exceeds cell limit; narrow scope")
    if output_format == "csv":
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
        output = io.BytesIO()
        pdf = canvas.Canvas(output, pagesize=(612, 792), pageCompression=1, invariant=1)
        pdf.setTitle("NANFO scoped report")
        y, pages = 754, 1
        pdf.setFont("Courier", 8)
        for row in [
            (
                "NANFO scoped snapshot. Unicode uses reversible JSON escapes; no text cropped.",
            ),
            *rows,
        ]:
            for line in textwrap.wrap(
                " | ".join(row),
                width=108,
                replace_whitespace=False,
                drop_whitespace=False,
            ) or [""]:
                if y < 38:
                    pdf.showPage()
                    pages += 1
                    if pages > 600:
                        raise ValueError("Report exceeds PDF page limit; narrow scope")
                    pdf.setFont("Courier", 8)
                    y = 754
                pdf.drawString(36, y, line)
                y -= 10
        pdf.save()
        data = output.getvalue()
    else:
        raise ValueError("Unsupported format")
    if not 0 < len(data) <= max_bytes:
        raise ValueError("Report exceeds byte limit; narrow scope")
    return data


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

    def read(self, report_id, output_format, receipt):
        name = self.filename(report_id, receipt["artifact_id"], output_format)
        if (
            receipt["filename"] != name
            or not 0 < receipt["size_bytes"] <= self.max_bytes
        ):
            raise ValueError("Invalid receipt")
        directory = self._directory()
        try:
            fd = os.open(
                name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
            )
        finally:
            os.close(directory)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or info.st_mode & 0o077
                or info.st_nlink != 1
            ):
                raise ValueError("Unsafe artifact")
            if info.st_size != receipt["size_bytes"]:
                raise ValueError("Artifact size mismatch")
            data = stream.read(self.max_bytes + 1)
        if (
            len(data) != receipt["size_bytes"]
            or hashlib.sha256(data).hexdigest() != receipt["checksum_sha256"]
        ):
            raise ValueError("Artifact checksum mismatch")
        # Stream verified immutable bytes, not a path that can change after validation.
        return data


def valid_receipt(record):
    receipt = getattr(record, "receipt", None)
    if getattr(record, "artifact_version", 0) != 1 or not isinstance(receipt, dict):
        return False
    try:
        return (
            record.status == "generated"
            and record.status_version >= 2
            and receipt["snapshot_sha256"]
            == record.snapshot_sha256
            == digest(record.snapshot)
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
