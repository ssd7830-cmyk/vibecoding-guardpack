#!/usr/bin/env python3
"""Build the v2.3 report from its template and the shipped Markdown files.

The appendix is always generated from the current README and 00-09 files so a
hand-edited PDF cannot silently drift from the package.  Chrome is only needed
when --pdf is requested; generating the synchronized HTML uses the standard
library only.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


VERSION = "2.3.7"
MARKER = "<!-- APPENDIX_FILES -->"
SOURCE_HASH_TOKEN = "{{APPENDIX_SOURCE_SET_SHA256}}"
APPENDIX_FILES = [
    "README.md",
    "00-글로벌-코어.md",
    "01-비가역-가드.md",
    "02-완료-검증-가드.md",
    "03-진단-수리-분리.md",
    "04-오염-차단.md",
    "05-정직-보고.md",
    "06-되묻기-기록.md",
    "07-한국어-가드.md",
    "08-분기-플레이북.md",
    "09-행동-회귀-테스트.md",
]
COMMON_CHROME_PATHS = [
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
]

FRONT_PAGE_IDS = {f"p{number}" for number in range(1, 16)}
FRONT_PAGE_PATTERN = re.compile(r'<section class="page(?: cover)?" id="(p\d+)">')
BANNED_FRONT_CLAIMS = (
    "Guardpack v2.2.0",
    "93 / 93",
    "지정 시나리오 작동 확인",
    "지정 행동 시나리오에서 작동을 확인",
    "AI 3종",
)


def appendix_source_set_hash(pack: Path) -> str:
    digest = hashlib.sha256()
    for relative in APPENDIX_FILES:
        source = pack / relative
        if not source.is_file():
            raise FileNotFoundError(f"appendix source missing: {relative}")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(source.read_bytes()).digest())
    return digest.hexdigest()


def validate_template(template: str) -> None:
    if template.count(MARKER) != 1:
        raise ValueError(f"template must contain exactly one {MARKER}")
    if template.count(SOURCE_HASH_TOKEN) != 1:
        raise ValueError(f"template must contain exactly one {SOURCE_HASH_TOKEN}")
    if VERSION not in template:
        raise ValueError(f"template does not identify v{VERSION}")
    page_ids = FRONT_PAGE_PATTERN.findall(template)
    if len(page_ids) != 15 or set(page_ids) != FRONT_PAGE_IDS:
        raise ValueError("template must contain exactly one student front page p1 through p15")
    front = template.split(MARKER, 1)[0]
    present = [claim for claim in BANNED_FRONT_CLAIMS if claim in front]
    if present:
        raise ValueError("template contains stale or unsupported front claim: " + ", ".join(present))


def render_appendix(pack: Path) -> str:
    sections: list[str] = []
    for relative in APPENDIX_FILES:
        source = pack / relative
        if not source.is_file():
            raise FileNotFoundError(f"appendix source missing: {relative}")
        body = source.read_text(encoding="utf-8")
        sections.append(
            '<section class="docfile">\n'
            f"<h3>{html.escape(relative)}</h3>\n"
            f'<pre class="mdfile">{html.escape(body)}</pre>\n'
            "</section>"
        )
    return "\n\n".join(sections)


def find_chrome(explicit: Path | None) -> Path:
    if explicit:
        candidate = explicit.expanduser().resolve()
        if not candidate.is_file():
            raise FileNotFoundError(f"Chrome executable not found: {candidate}")
        return candidate
    for candidate in COMMON_CHROME_PATHS:
        if candidate.is_file():
            return candidate
    for name in ("google-chrome", "chromium", "chromium-browser"):
        discovered = shutil.which(name)
        if discovered:
            return Path(discovered)
    raise FileNotFoundError("Chrome/Chromium not found; pass --chrome")


def build_html(pack: Path, output: Path) -> None:
    if output.is_symlink():
        raise RuntimeError(f"refusing to replace a symlink HTML target: {output}")
    if output.exists() and (not output.is_file() or output.stat().st_nlink > 1):
        raise RuntimeError(f"refusing to replace a non-regular or hard-linked HTML target: {output}")
    template_path = pack / "docs" / "report.template.html"
    if not template_path.is_file():
        raise FileNotFoundError(f"report template missing: {template_path}")
    template = template_path.read_text(encoding="utf-8")
    validate_template(template)
    rendered = template.replace(SOURCE_HASH_TOKEN, appendix_source_set_hash(pack))
    rendered = rendered.replace(MARKER, render_appendix(pack))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".guardpack-html-", dir=output.parent) as workspace:
        staged_html = Path(workspace) / "report.html"
        staged_html.write_text(rendered, encoding="utf-8")
        staged_html.replace(output)


def lexical_absolute(path: Path) -> Path:
    expanded = path.expanduser()
    return expanded if expanded.is_absolute() else Path(os.path.abspath(expanded))


def build_pdf(chrome: Path, html_path: Path, pdf_path: Path) -> None:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    if pdf_path.is_symlink():
        raise RuntimeError(f"refusing to replace a symlink PDF target: {pdf_path}")
    if pdf_path.exists() and (not pdf_path.is_file() or pdf_path.stat().st_nlink > 1):
        raise RuntimeError(f"refusing to replace a non-regular or hard-linked PDF target: {pdf_path}")
    with tempfile.TemporaryDirectory(prefix=".guardpack-pdf-", dir=pdf_path.parent) as workspace:
        workspace_path = Path(workspace)
        staged_pdf = workspace_path / "report.pdf"
        profile = workspace_path / "chrome-profile"
        command = [
            str(chrome),
            "--headless",
            "--disable-gpu",
            "--disable-extensions",
            "--disable-background-networking",
            "--no-first-run",
            "--no-default-browser-check",
            "--no-pdf-header-footer",
            "--run-all-compositor-stages-before-draw",
            "--virtual-time-budget=10000",
            f"--user-data-dir={profile}",
            f"--print-to-pdf={staged_pdf}",
            html_path.resolve().as_uri(),
        ]
        try:
            result = subprocess.run(command, text=True, capture_output=True, timeout=45)
        except subprocess.TimeoutExpired:
            # Some macOS Chrome builds finish writing a valid PDF but keep the
            # browser process alive. The timeout kills that process; the file
            # still must pass the same fresh-path, size, header and EOF checks.
            result = None
        if result is not None and result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"Chrome PDF build failed ({result.returncode}): {detail}")
        if not staged_pdf.is_file() or staged_pdf.stat().st_size < 256:
            raise RuntimeError("Chrome returned success but no new plausible PDF was produced")
        with staged_pdf.open("rb") as handle:
            header = handle.read(5)
            handle.seek(max(0, staged_pdf.stat().st_size - 2048))
            tail = handle.read()
        if header != b"%PDF-" or b"%%EOF" not in tail:
            raise RuntimeError("Chrome output does not have a valid PDF header and trailer")
        staged_pdf.replace(pdf_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--html", type=Path, required=True)
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--chrome", type=Path)
    args = parser.parse_args()

    try:
        pack = args.pack.expanduser().resolve()
        html_path = lexical_absolute(args.html)
        build_html(pack, html_path)
        print(f"HTML: {html_path}")
        if args.pdf:
            pdf_path = lexical_absolute(args.pdf)
            build_pdf(find_chrome(args.chrome), html_path, pdf_path)
            print(f"PDF: {pdf_path}")
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
