"""Presentation packs copy exact allowlisted evidence files, never directory sweeps (ADR-028)."""

from pathlib import Path
import tempfile
import unittest

import presentation


class AllowlistedCopyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir="/tmp/opencode")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "test-ppo"
        self.source.mkdir()
        for name in presentation.SESSION_FILES:
            (self.source / name).write_text(name)
        for name in (".env", "signing.key", "notes.log"):
            (self.source / name).write_text("private")
        (self.source / "nested").mkdir()
        (self.source / "nested" / "manifest.json").write_text("{}")

    def test_only_named_regular_files_are_copied(self):
        target = self.root / "pack" / "test-ppo"
        target.parent.mkdir()
        presentation.copyAllowlisted(self.source, target, presentation.SESSION_FILES)
        self.assertEqual(sorted(p.name for p in target.iterdir()), sorted(presentation.SESSION_FILES))
        for name in presentation.SESSION_FILES:
            self.assertEqual((target / name).read_text(), name)

    def test_missing_or_linked_allowlisted_file_is_refused(self):
        (self.source / "progress.json").unlink()
        (self.source / "progress.json").symlink_to(self.source / "summary.json")
        with self.assertRaisesRegex(ValueError, "Allowlisted evidence missing: progress.json"):
            presentation.copyAllowlisted(self.source, self.root / "linked", presentation.SESSION_FILES)
        (self.source / "progress.json").unlink()
        with self.assertRaisesRegex(ValueError, "Allowlisted evidence missing"):
            presentation.copyAllowlisted(self.source, self.root / "missing", presentation.SESSION_FILES)


if __name__ == "__main__":
    unittest.main()
