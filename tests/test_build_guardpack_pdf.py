#!/usr/bin/env python3
"""HTML synchronization tests for the PDF builder (Chrome not required)."""

from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

import sys


PACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACK))

from build_guardpack_pdf import (  # noqa: E402
    APPENDIX_FILES,
    MARKER,
    SOURCE_HASH_TOKEN,
    appendix_source_set_hash,
    build_html,
    build_pdf,
    main,
)


class BuildGuardpackPdfTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="guardpack-pdf-test-")
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_html_contains_exact_current_markdown_appendix(self) -> None:
        output = self.root / "report.html"
        build_html(PACK, output)
        rendered = output.read_text(encoding="utf-8")
        self.assertNotIn(MARKER, rendered)
        self.assertNotIn(SOURCE_HASH_TOKEN, rendered)
        self.assertIn(appendix_source_set_hash(PACK), rendered)
        for relative in APPENDIX_FILES:
            body = (PACK / relative).read_text(encoding="utf-8")
            self.assertIn(f"<h3>{html.escape(relative)}</h3>", rendered)
            self.assertIn(html.escape(body), rendered)

    def test_student_front_is_single_versioned_source_without_behavior_overclaim(self) -> None:
        template = (PACK / "docs" / "report.template.html").read_text(encoding="utf-8")
        page_ids = re.findall(r'<section class="page(?: cover)?" id="(p\d+)">', template)
        self.assertEqual(sorted(page_ids, key=lambda value: int(value[1:])), [f"p{i}" for i in range(1, 16)])
        self.assertEqual(len(page_ids), len(set(page_ids)))
        self.assertEqual(template.count(MARKER), 1)
        self.assertIn("Guardpack v2.3.7", template)
        self.assertIn("guardpack/versions/2.3.7/00-글로벌-코어.md", template)
        self.assertIn("APPENDIX · v2.3.7 동기화 원문", template)
        self.assertNotIn("v2.3.2", template)
        self.assertNotIn("v2.3.3", template)
        self.assertNotIn("v2.3.4", template)
        self.assertNotIn("v2.3.5", template)
        self.assertNotIn("v2.3.6", template)
        self.assertIn("채점된 실제 모델 비교가 끝나기 전", template)
        self.assertIn("문구 트리거 1 + 자동 라우터 4 + 수동 감사 1", template)
        for stale_or_overclaim in (
            "Guardpack v2.2.0",
            "93 / 93",
            "지정 시나리오 작동 확인",
            "지정 행동 시나리오에서 작동을 확인",
            "AI 3종",
        ):
            self.assertNotIn(stale_or_overclaim, template)

    def test_duplicate_template_marker_is_rejected(self) -> None:
        candidate = self.root / "pack"
        shutil.copytree(PACK, candidate)
        template = candidate / "docs" / "report.template.html"
        template.write_text(
            template.read_text(encoding="utf-8") + "\n" + MARKER + "\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "exactly one"):
            build_html(candidate, self.root / "bad.html")

    def test_missing_appendix_source_is_rejected(self) -> None:
        candidate = self.root / "pack"
        shutil.copytree(PACK, candidate)
        (candidate / "09-행동-회귀-테스트.md").unlink()
        with self.assertRaisesRegex(FileNotFoundError, "appendix source missing"):
            build_html(candidate, self.root / "bad.html")

    def test_chrome_exit_zero_without_new_output_cannot_reuse_stale_pdf(self) -> None:
        html_path = self.root / "report.html"
        html_path.write_text("<html></html>\n", encoding="utf-8")
        pdf_path = self.root / "report.pdf"
        stale = b"stale-not-a-pdf\n"
        pdf_path.write_bytes(stale)
        completed = subprocess.CompletedProcess(["fake-chrome"], 0, "", "")
        with mock.patch("build_guardpack_pdf.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(RuntimeError, "no new plausible PDF"):
                build_pdf(Path("/fake/chrome"), html_path, pdf_path)
        self.assertEqual(pdf_path.read_bytes(), stale)

    def test_chrome_timeout_accepts_only_a_complete_fresh_pdf(self) -> None:
        html_path = self.root / "report.html"
        html_path.write_text("<html></html>\n", encoding="utf-8")
        pdf_path = self.root / "report.pdf"

        def write_then_timeout(command: list[str], **_: object) -> object:
            staged = next(item.split("=", 1)[1] for item in command if item.startswith("--print-to-pdf="))
            Path(staged).write_bytes(b"%PDF-1.4\n" + b"x" * 300 + b"\n%%EOF\n")
            raise subprocess.TimeoutExpired(command, 45)

        with mock.patch("build_guardpack_pdf.subprocess.run", side_effect=write_then_timeout):
            build_pdf(Path("/fake/chrome"), html_path, pdf_path)
        self.assertTrue(pdf_path.read_bytes().startswith(b"%PDF-"))

    def test_cli_does_not_follow_pdf_output_symlink(self) -> None:
        html_path = self.root / "report.html"
        valuable = self.root / "valuable.pdf"
        valuable.write_bytes(b"valuable original\n")
        link = self.root / "output.pdf"
        link.symlink_to(valuable)
        arguments = [
            "build_guardpack_pdf.py", "--pack", str(PACK), "--html", str(html_path),
            "--pdf", str(link), "--chrome", "/fake/chrome",
        ]
        output = StringIO()
        with mock.patch("sys.argv", arguments), mock.patch(
            "build_guardpack_pdf.find_chrome", return_value=Path("/fake/chrome")
        ), redirect_stdout(output), redirect_stderr(output):
            result = main()
        self.assertEqual(result, 1)
        self.assertIn("symlink PDF target", output.getvalue())
        self.assertTrue(link.is_symlink())
        self.assertEqual(valuable.read_bytes(), b"valuable original\n")

    def test_cli_does_not_follow_html_output_symlink(self) -> None:
        valuable = self.root / "valuable.html"
        valuable.write_text("valuable original\n", encoding="utf-8")
        link = self.root / "output.html"
        link.symlink_to(valuable)
        arguments = ["build_guardpack_pdf.py", "--pack", str(PACK), "--html", str(link)]
        output = StringIO()
        with mock.patch("sys.argv", arguments), redirect_stdout(output), redirect_stderr(output):
            result = main()
        self.assertEqual(result, 1)
        self.assertIn("symlink HTML target", output.getvalue())
        self.assertTrue(link.is_symlink())
        self.assertEqual(valuable.read_text(encoding="utf-8"), "valuable original\n")

    def test_html_hard_link_target_is_refused(self) -> None:
        peer = self.root / "peer.html"
        peer.write_text("valuable original\n", encoding="utf-8")
        output = self.root / "output.html"
        os.link(peer, output)
        with self.assertRaisesRegex(RuntimeError, "hard-linked HTML target"):
            build_html(PACK, output)
        self.assertEqual(peer.read_text(encoding="utf-8"), "valuable original\n")


if __name__ == "__main__":
    unittest.main()
