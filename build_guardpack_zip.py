#!/usr/bin/env python3
"""Build one deterministic UTF-8-safe student distribution ZIP."""

from __future__ import annotations

import argparse
import os
import stat
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_guardpack import REQUIRED  # noqa: E402


VERSION = "2.3.7"
OUTER = "바이브코딩-가드팩-배포"
INNER = "바이브코딩-가드팩"
HELPER = Path("docs/release-helper.md")
START_GUIDE = Path("docs/시작하기.txt")
START_GUIDE_NAME = "시작하기.txt"
FIXED_TIME = (2026, 8, 25, 0, 0, 0)
SKIP_PARTS = {"__pycache__", ".pytest_cache", ".git"}
SKIP_NAMES = {".DS_Store", ".gitignore", "LICENSE"}


def safe_output(path: Path) -> None:
    if path.is_symlink():
        raise RuntimeError(f"refusing symlink ZIP output: {path}")
    if path.exists() and (not path.is_file() or path.stat().st_nlink > 1):
        raise RuntimeError(f"refusing non-regular or hard-linked ZIP output: {path}")


def source_files(pack: Path) -> list[Path]:
    if not pack.is_dir() or pack.is_symlink():
        raise RuntimeError(f"pack must be a regular directory: {pack}")
    files: list[Path] = []
    for path in sorted(pack.rglob("*"), key=lambda item: item.relative_to(pack).as_posix()):
        relative = path.relative_to(pack)
        if any(part in SKIP_PARTS for part in relative.parts) or path.name in SKIP_NAMES:
            continue
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise RuntimeError(f"refusing symlink pack entry: {relative}")
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise RuntimeError(f"refusing unsafe pack entry: {relative}")
        files.append(path)
    if not files:
        raise RuntimeError("pack contains no files")
    shipped = {path.relative_to(pack).as_posix() for path in files}
    required = set(REQUIRED)
    extra = sorted(shipped - required)
    missing = sorted(required - shipped)
    if extra:
        shown = ", ".join(extra[:10]) + (f" (+{len(extra) - 10} more)" if len(extra) > 10 else "")
        raise RuntimeError(f"refusing files outside the release manifest: {shown}")
    if missing:
        raise RuntimeError("release manifest files missing: " + ", ".join(missing[:10]))
    helper = pack / HELPER
    if helper not in files:
        raise RuntimeError(f"release helper missing: {HELPER}")
    first_line = helper.read_text(encoding="utf-8").splitlines()[0]
    if f"v{VERSION}" not in first_line:
        raise RuntimeError(f"release helper does not identify v{VERSION}")
    guide = pack / START_GUIDE
    if guide not in files:
        raise RuntimeError(f"start guide missing: {START_GUIDE}")
    if f"v{VERSION}" not in guide.read_text(encoding="utf-8").splitlines()[0]:
        raise RuntimeError(f"start guide does not identify v{VERSION}")
    return files


def zip_info(name: str, directory: bool = False) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name + ("/" if directory and not name.endswith("/") else ""), FIXED_TIME)
    info.create_system = 3
    mode = (stat.S_IFDIR | 0o755) if directory else (stat.S_IFREG | 0o644)
    info.external_attr = mode << 16
    info.compress_type = zipfile.ZIP_STORED if directory else zipfile.ZIP_DEFLATED
    return info


def build_release_zip(pack: Path, output: Path) -> None:
    pack = pack.expanduser().resolve()
    output = output.expanduser().absolute()
    safe_output(output)
    files = source_files(pack)
    helper_bytes = (pack / HELPER).read_bytes()
    guide_bytes = (pack / START_GUIDE).read_bytes()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".guardpack-zip-", dir=output.parent) as workspace:
        staged = Path(workspace) / "release.zip"
        with zipfile.ZipFile(staged, "w", allowZip64=True) as archive:
            archive.writestr(zip_info(OUTER, directory=True), b"")
            archive.writestr(zip_info(f"{OUTER}/{INNER}", directory=True), b"")
            archive.writestr(zip_info(f"{OUTER}/CLAUDE.md"), helper_bytes, compresslevel=9)
            archive.writestr(zip_info(f"{OUTER}/{START_GUIDE_NAME}"), guide_bytes, compresslevel=9)
            for source in files:
                relative = source.relative_to(pack).as_posix()
                archive.writestr(
                    zip_info(f"{OUTER}/{INNER}/{relative}"),
                    source.read_bytes(),
                    compresslevel=9,
                )
        verify_release_zip(staged, pack)
        staged.replace(output)


def verify_release_zip(path: Path, pack: Path | None = None) -> None:
    with zipfile.ZipFile(path) as archive, path.open("rb") as raw:
        infos = archive.infolist()
        if len(infos) != len({info.filename for info in infos}):
            raise RuntimeError("ZIP contains duplicate names")
        for info in infos:
            parts = Path(info.filename.rstrip("/")).parts
            if not parts or parts[0] != OUTER or info.filename.startswith("/") or ".." in parts:
                raise RuntimeError(f"unsafe ZIP member: {info.filename}")
            if "\\" in info.filename:
                raise RuntimeError(f"non-portable ZIP separator: {info.filename}")
            if info.flag_bits & 0x800 == 0:
                raise RuntimeError(f"central directory lacks UTF-8 EFS flag: {info.filename}")
            raw.seek(info.header_offset + 6)
            local_flags = int.from_bytes(raw.read(2), "little")
            if local_flags & 0x800 == 0:
                raise RuntimeError(f"local header lacks UTF-8 EFS flag: {info.filename}")
            unix_type = (info.external_attr >> 16) & 0o170000
            if unix_type == stat.S_IFLNK:
                raise RuntimeError(f"ZIP contains symlink: {info.filename}")
        names = {info.filename for info in infos}
        if f"{OUTER}/CLAUDE.md" not in names:
            raise RuntimeError("outer release helper missing")
        if f"{OUTER}/{START_GUIDE_NAME}" not in names:
            raise RuntimeError("outer start guide missing")
        if pack is not None:
            expected = {
                f"{OUTER}/{INNER}/{source.relative_to(pack).as_posix()}"
                for source in source_files(pack)
            }
            actual_files = {
                info.filename
                for info in infos
                if not info.is_dir()
                and info.filename not in (f"{OUTER}/CLAUDE.md", f"{OUTER}/{START_GUIDE_NAME}")
            }
            if actual_files != expected:
                raise RuntimeError("ZIP pack inventory differs from source")
            for source in source_files(pack):
                member = f"{OUTER}/{INNER}/{source.relative_to(pack).as_posix()}"
                if archive.read(member) != source.read_bytes():
                    raise RuntimeError(f"ZIP payload differs from source: {member}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        build_release_zip(args.pack, args.output)
        print(f"ZIP: {args.output.expanduser().absolute()}")
    except (OSError, RuntimeError, UnicodeError, zipfile.BadZipFile) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
