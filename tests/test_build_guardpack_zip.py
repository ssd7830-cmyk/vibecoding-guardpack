#!/usr/bin/env python3
"""Regression tests for deterministic UTF-8 release ZIP generation."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

import sys


PACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACK))

from build_guardpack_zip import INNER, OUTER, START_GUIDE_NAME, build_release_zip, verify_release_zip  # noqa: E402


class BuildGuardpackZipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="guardpack-release-zip-test-")
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_release_zip_has_utf8_in_local_and_central_headers(self) -> None:
        output = self.root / "release.zip"
        build_release_zip(PACK, output)
        verify_release_zip(output, PACK)
        with zipfile.ZipFile(output) as archive, output.open("rb") as raw:
            infos = archive.infolist()
            self.assertTrue(infos)
            for info in infos:
                self.assertTrue(info.flag_bits & 0x800, info.filename)
                raw.seek(info.header_offset + 6)
                self.assertTrue(int.from_bytes(raw.read(2), "little") & 0x800, info.filename)
            self.assertIn(f"{OUTER}/CLAUDE.md", archive.namelist())
            self.assertIn(f"{OUTER}/{START_GUIDE_NAME}", archive.namelist())
            self.assertEqual(archive.read(f"{OUTER}/{START_GUIDE_NAME}"), (PACK / "docs" / START_GUIDE_NAME).read_bytes())
            self.assertIn(f"{OUTER}/{INNER}/README.md", archive.namelist())

    def test_two_builds_are_byte_identical(self) -> None:
        first = self.root / "first.zip"
        second = self.root / "second.zip"
        build_release_zip(PACK, first)
        build_release_zip(PACK, second)
        self.assertEqual(hashlib.sha256(first.read_bytes()).digest(), hashlib.sha256(second.read_bytes()).digest())

    def test_files_outside_release_manifest_are_refused(self) -> None:
        # AUD-DEP-01: a developer's .env/.git must never ride along into the student ZIP.
        candidate = self.root / "pack"
        shutil.copytree(
            PACK,
            candidate,
            ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".DS_Store"),
        )
        (candidate / ".env").write_text("SECRET=1\n", encoding="utf-8")
        output = self.root / "release.zip"
        with self.assertRaisesRegex(RuntimeError, "outside the release manifest"):
            build_release_zip(candidate, output)
        self.assertFalse(output.exists())

    def test_symlink_output_is_refused_without_touching_target(self) -> None:
        valuable = self.root / "valuable.zip"
        valuable.write_bytes(b"valuable\n")
        link = self.root / "release.zip"
        link.symlink_to(valuable)
        with self.assertRaisesRegex(RuntimeError, "symlink ZIP output"):
            build_release_zip(PACK, link)
        self.assertEqual(valuable.read_bytes(), b"valuable\n")


if __name__ == "__main__":
    unittest.main()
