#!/usr/bin/env python3
"""Plan or perform a conservative user-scope guardpack installation.

The default is read-only. --apply installs an immutable version directory and
updates only the managed marker block in the user CLAUDE.md after preflight.
It never changes permissions, sandbox, hooks, model selection, or unrelated
imports, and it refuses to write when known legacy fingerprint candidates are reachable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shlex
import shutil
import stat
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from verify_guardpack import (
    BEGIN_MARKER,
    CORE_POLICY_BASELINE_VERSION,
    END_MARKER,
    EXPECTED_IMPORT,
    LEGACY_CONFLICT_FINGERPRINTS,
    REQUIRED,
    VERSION,
    collect_import_graph,
    import_tokens,
    normalized_visible,
    regular_tree_inventory,
    scan_routing_candidates,
    sha256 as stable_sha256,
    unscoped_rules,
)


def digest(path: Path) -> str:
    return stable_sha256(path)


def default_config_root() -> Path:
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".claude"


def lexical_absolute(path: Path) -> Path:
    expanded = path.expanduser()
    return expanded if expanded.is_absolute() else Path(os.path.abspath(expanded))


def require_anchored_fs_support() -> None:
    required_dir_fd = (os.open, os.mkdir, os.stat, os.rename, os.link, os.unlink)
    if any(function not in os.supports_dir_fd for function in required_dir_fd):
        raise OSError(
            "runtime lacks required dir_fd filesystem operations "
            "(Windows 네이티브 Python 미지원 — WSL 또는 macOS/Linux에서 설치)"
        )
    if os.stat not in os.supports_follow_symlinks or os.link not in os.supports_follow_symlinks:
        raise OSError("runtime lacks required no-follow filesystem operations")
    for flag in ("O_NOFOLLOW", "O_DIRECTORY", "O_CLOEXEC"):
        if not hasattr(os, flag):
            raise OSError(f"runtime lacks required {flag}")


def directory_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def open_physical_directory(path: Path, create: bool) -> int:
    """Open an absolute path component-by-component without following symlinks."""
    require_anchored_fs_support()
    if not path.is_absolute() or path == Path("/"):
        raise OSError(f"config root must be a non-root absolute path: {path}")
    current = os.open("/", directory_flags())
    try:
        for component in path.parts[1:]:
            if component in ("", ".", "..") or "/" in component:
                raise OSError(f"unsafe path component: {component!r}")
            try:
                child = os.open(component, directory_flags(), dir_fd=current)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(component, 0o700, dir_fd=current)
                child = os.open(component, directory_flags(), dir_fd=current)
                os.fchmod(child, 0o700)
            metadata = os.fstat(child)
            if not stat.S_ISDIR(metadata.st_mode):
                os.close(child)
                raise OSError(f"path component is not a directory: {component}")
            os.close(current)
            current = child
        final = os.fstat(current)
        if final.st_uid != os.geteuid() or final.st_mode & 0o022:
            raise OSError("config root must be owned by the current user and not group/world-writable")
        return current
    except Exception:
        os.close(current)
        raise


def open_child_directory(parent_fd: int, name: str, create: bool, private: bool = False) -> int:
    if not name or name in (".", "..") or "/" in name:
        raise OSError(f"unsafe directory leaf: {name!r}")
    try:
        child = os.open(name, directory_flags(), dir_fd=parent_fd)
    except FileNotFoundError:
        if not create:
            raise
        os.mkdir(name, 0o700, dir_fd=parent_fd)
        child = os.open(name, directory_flags(), dir_fd=parent_fd)
        os.fchmod(child, 0o700 if private else 0o755)
    metadata = os.fstat(child)
    entry = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or (metadata.st_dev, metadata.st_ino) != (entry.st_dev, entry.st_ino)
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o022
    ):
        os.close(child)
        raise OSError(f"unsafe managed directory topology: {name}")
    return child


def assert_directory_entry(parent_fd: int, name: str, child_fd: int) -> None:
    held = os.fstat(child_fd)
    entry = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if (
        not stat.S_ISDIR(entry.st_mode)
        or (held.st_dev, held.st_ino) != (entry.st_dev, entry.st_ino)
    ):
        raise ConcurrentChangeError(f"managed directory entry changed: {name}")


def assert_config_root_entry(config_root: Path, config_fd: int) -> None:
    held = os.fstat(config_fd)
    entry = os.lstat(config_root)
    if (
        not stat.S_ISDIR(entry.st_mode)
        or (held.st_dev, held.st_ino) != (entry.st_dev, entry.st_ino)
    ):
        raise ConcurrentChangeError("config root namespace entry changed")


def assert_managed_tree(
    config_root: Path,
    config_fd: int,
    guardpack_fd: int,
    versions_fd: int,
    backups_fd: int,
    version_fd: int | None = None,
) -> None:
    assert_config_root_entry(config_root, config_fd)
    assert_directory_entry(config_fd, "guardpack", guardpack_fd)
    assert_directory_entry(guardpack_fd, "versions", versions_fd)
    assert_directory_entry(guardpack_fd, "backups", backups_fd)
    if version_fd is not None:
        assert_directory_entry(versions_fd, VERSION, version_fd)


def read_regular_at(parent_fd: int, name: str, expected_links: int = 1) -> tuple[bytes, os.stat_result]:
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open(name, flags, dir_fd=parent_fd)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != expected_links:
            raise OSError(f"{name} is not a {expected_links}-link regular file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        entry = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            metadata_signature(before) != metadata_signature(after)
            or (after.st_dev, after.st_ino) != (entry.st_dev, entry.st_ino)
        ):
            raise ConcurrentChangeError(f"{name} changed while it was being read")
        return b"".join(chunks), after
    finally:
        os.close(descriptor)


def write_new_file_at(parent_fd: int, name: str, body: bytes, mode: int) -> os.stat_result:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open(name, flags, mode, dir_fd=parent_fd)
    try:
        os.fchmod(descriptor, mode)
        view = memoryview(body)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise OSError(f"new file has unsafe topology: {name}")
        return metadata
    finally:
        os.close(descriptor)


def read_source_snapshot(pack: Path) -> dict[str, bytes]:
    snapshot: dict[str, bytes] = {}
    for relative in REQUIRED:
        source = pack / relative
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
        descriptor = os.open(source, flags)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise OSError(f"package source is not a single-link regular file: {relative}")
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 65536)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(descriptor)
            entry = source.lstat()
            if (
                metadata_signature(before) != metadata_signature(after)
                or (after.st_dev, after.st_ino) != (entry.st_dev, entry.st_ino)
            ):
                raise ConcurrentChangeError(f"package source changed while reading: {relative}")
            snapshot[relative] = b"".join(chunks)
        finally:
            os.close(descriptor)
    return snapshot


def open_relative_directory(root_fd: int, parts: tuple[str, ...], create: bool) -> int:
    current = os.dup(root_fd)
    try:
        for part in parts:
            child = open_child_directory(current, part, create=create)
            os.close(current)
            current = child
        return current
    except Exception:
        os.close(current)
        raise


def collect_version_tree(root_fd: int, prefix: str = "") -> tuple[dict[str, bytes], list[str]]:
    files: dict[str, bytes] = {}
    problems: list[str] = []
    for name in sorted(os.listdir(root_fd)):
        relative = f"{prefix}/{name}" if prefix else name
        try:
            metadata = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                child = open_child_directory(root_fd, name, create=False)
                try:
                    child_files, child_problems = collect_version_tree(child, relative)
                    files.update(child_files)
                    problems.extend(child_problems)
                finally:
                    os.close(child)
            elif stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
                body, _ = read_regular_at(root_fd, name)
                files[relative] = body
            else:
                problems.append(f"installed entry has unsafe type/topology: {relative}")
        except (OSError, ConcurrentChangeError) as error:
            problems.append(f"installed entry cannot be verified: {relative}: {error}")
    return files, problems


def verify_version_at(version_fd: int, snapshot: dict[str, bytes]) -> list[str]:
    actual, problems = collect_version_tree(version_fd)
    expected_names = set(snapshot)
    actual_names = set(actual)
    for relative in sorted(expected_names - actual_names):
        problems.append(f"installed file missing: {relative}")
    for relative in sorted(actual_names - expected_names):
        problems.append(f"installed extra file: {relative}")
    for relative in sorted(expected_names & actual_names):
        if actual[relative] != snapshot[relative]:
            problems.append(f"installed hash differs: {relative}")
    return problems


def open_or_install_version(versions_fd: int, snapshot: dict[str, bytes]) -> tuple[int, str]:
    try:
        version_fd = open_child_directory(versions_fd, VERSION, create=False)
        state = "identical; reuse"
    except FileNotFoundError:
        version_fd = open_child_directory(versions_fd, VERSION, create=True)
        state = "installed"
        try:
            for relative, body in snapshot.items():
                path = Path(relative)
                parent = open_relative_directory(version_fd, path.parts[:-1], create=True)
                try:
                    write_new_file_at(parent, path.name, body, 0o644)
                finally:
                    os.close(parent)
        except Exception:
            os.close(version_fd)
            raise
    differences = verify_version_at(version_fd, snapshot)
    if differences:
        os.close(version_fd)
        raise OSError("version verification failed: " + "; ".join(differences))
    return version_fd, state


def secure_backup_at(
    backups_fd: int,
    config_root: Path,
    existing_bytes: bytes | None,
    previous_mode: int | None,
    planned_bytes: bytes,
) -> tuple[Path, int]:
    for _ in range(32):
        leaf = datetime.now().strftime("%Y%m%d-%H%M%S-%f-") + secrets.token_hex(4)
        try:
            os.mkdir(leaf, 0o700, dir_fd=backups_fd)
            break
        except FileExistsError:
            continue
    else:
        raise OSError("could not allocate a unique backup transaction")
    transaction_fd = open_child_directory(backups_fd, leaf, create=False, private=True)
    if existing_bytes is not None:
        write_new_file_at(transaction_fd, "CLAUDE.md", existing_bytes, 0o600)
    manifest = {
        "schema_version": 2,
        "operation_id": leaf,
        "status": "prepared",
        "guardpack_version": VERSION,
        "config_root": str(config_root),
        "global_memory_path": str(config_root / "CLAUDE.md"),
        "version_target": str(config_root / "guardpack" / "versions" / VERSION),
        "created_at_local": datetime.now().astimezone().isoformat(),
        "preimage": {
            "existed": existing_bytes is not None,
            "sha256": hashlib.sha256(existing_bytes or b"").hexdigest(),
            "size": len(existing_bytes or b""),
            "mode": stat.S_IMODE(previous_mode) if previous_mode is not None else None,
        },
        "expected_activation": {
            "sha256": hashlib.sha256(planned_bytes).hexdigest(),
            "size": len(planned_bytes),
            "managed_import": EXPECTED_IMPORT,
        },
    }
    write_new_file_at(
        transaction_fd,
        "manifest.json",
        (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        0o600,
    )
    return config_root / "guardpack" / "backups" / leaf, transaction_fd


def config_topology_problems(config_root: Path) -> list[str]:
    """Reject redirection through symlink/non-directory managed ancestors."""
    problems: list[str] = []
    managed = (
        (config_root, "config root"),
        (config_root / "guardpack", "guardpack directory"),
        (config_root / "guardpack" / "versions", "versions directory"),
        (config_root / "guardpack" / "backups", "backups directory"),
    )
    for path, label in managed:
        if not os.path.lexists(path):
            continue
        try:
            metadata = os.lstat(path)
        except OSError as error:
            problems.append(f"{label} cannot be inspected: {path}: {error}")
            continue
        if stat.S_ISLNK(metadata.st_mode):
            problems.append(f"{label} is a symlink; refusing redirected writes: {path}")
        elif not stat.S_ISDIR(metadata.st_mode):
            problems.append(f"{label} is not a directory: {path}")
    nearest = config_root
    while not os.path.lexists(nearest) and nearest != nearest.parent:
        nearest = nearest.parent
    if os.path.lexists(nearest):
        try:
            metadata = os.lstat(nearest)
            if not stat.S_ISDIR(metadata.st_mode):
                problems.append(f"nearest existing config ancestor is not a directory: {nearest}")
            elif not os.access(nearest, os.W_OK | os.X_OK):
                problems.append(f"nearest existing config ancestor is not writable: {nearest}")
        except OSError as error:
            problems.append(f"config ancestor cannot be inspected: {nearest}: {error}")
    return problems


def is_guardpack_core_import(raw: str) -> bool:
    normalized = raw.replace("\\", "/")
    return "/guardpack/versions/" in "/" + normalized and normalized.endswith(
        "/00-글로벌-코어.md"
    )


def marker_positions(text: str) -> tuple[int, int] | None:
    begin_count = text.count(BEGIN_MARKER)
    end_count = text.count(END_MARKER)
    if begin_count == 0 and end_count == 0:
        if any(is_guardpack_core_import(raw) for raw in import_tokens(text)):
            raise ValueError("guardpack core import exists without the managed marker block")
        return None
    if begin_count != 1 or end_count != 1:
        raise ValueError("managed marker counts are not exactly one begin and one end")
    begin, end = text.index(BEGIN_MARKER), text.index(END_MARKER)
    if begin >= end:
        raise ValueError("managed markers are reversed")
    managed = text[begin + len(BEGIN_MARKER) : end]
    managed_lines = [line.strip() for line in managed.splitlines() if line.strip()]
    if len(managed_lines) != 1 or not managed_lines[0].startswith("@") or not is_guardpack_core_import(
        managed_lines[0][1:]
    ):
        raise ValueError("managed block contains content other than one guardpack core import")
    all_guardpack_imports = [raw for raw in import_tokens(text) if is_guardpack_core_import(raw)]
    if len(all_guardpack_imports) != 1:
        raise ValueError("guardpack core imports exist outside or duplicate the managed block")
    return begin, end


def managed_block() -> str:
    return f"{BEGIN_MARKER}\n{EXPECTED_IMPORT}\n{END_MARKER}"


def planned_global_text(existing: str) -> str:
    positions = marker_positions(existing)
    block = managed_block()
    if positions is None:
        if not existing:
            return block + "\n"
        separator = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
        return existing + separator + block + "\n"
    begin, end = positions
    end_after = end + len(END_MARKER)
    return existing[:begin] + block + existing[end_after:]


def validate_pack(pack: Path) -> list[str]:
    problems: list[str] = []
    for relative in REQUIRED:
        if not (pack / relative).is_file():
            problems.append(f"package file missing: {relative}")
    core = pack / "00-글로벌-코어.md"
    if core.is_file():
        try:
            lines = core.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as error:
            problems.append(f"package core cannot be read as UTF-8: {error}")
        else:
            if not lines or CORE_POLICY_BASELINE_VERSION not in lines[0]:
                problems.append(
                    "package core does not identify the frozen policy baseline "
                    f"{CORE_POLICY_BASELINE_VERSION}"
                )
    return problems


def compare_installed(pack: Path, installed: Path) -> list[str]:
    differences: list[str] = []
    installed_files, inventory_problems = regular_tree_inventory(installed)
    differences.extend(inventory_problems)
    required_files = set(REQUIRED)
    for relative in sorted(required_files - installed_files):
        differences.append(f"installed file missing: {relative}")
    for relative in sorted(installed_files - required_files):
        differences.append(f"installed extra file: {relative}")
    for relative in REQUIRED:
        source, target = pack / relative, installed / relative
        try:
            if target.is_symlink():
                differences.append(f"installed path is a symlink: {relative}")
            elif not target.is_file():
                differences.append(f"installed file missing: {relative}")
            elif target.stat().st_nlink > 1:
                differences.append(f"installed path is a hard link: {relative}")
            elif source.is_file() and digest(source) != digest(target):
                differences.append(f"installed hash differs: {relative}")
        except OSError as error:
            differences.append(f"installed file could not be verified: {relative}: {error}")
    return differences


def known_conflicts(
    global_path: Path | None, rules_dir: Path
) -> tuple[list[str], list[str]]:
    scratch_failures: list[str] = []
    warnings: list[str] = []
    roots: list[tuple[Path, str]] = []
    if global_path is not None:
        roots.append((global_path, "user memory"))
    roots.extend(unscoped_rules(rules_dir, warnings))
    sources = collect_import_graph(roots, scratch_failures)
    problems = list(scratch_failures)
    for source, body in sources:
        normalized = normalized_visible(body)
        for label, fragments in LEGACY_CONFLICT_FINGERPRINTS.items():
            if any(fragment in normalized for fragment in fragments):
                problems.append(
                    f"statically reachable legacy fingerprint candidate '{label}' in {source.path}"
                )
    return sorted(set(problems)), warnings


def copy_version(pack: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{VERSION}-", dir=target.parent))
    try:
        shutil.copytree(
            pack,
            staging,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
        )
        differences = compare_installed(pack, staging)
        if differences:
            raise OSError("staged copy verification failed: " + "; ".join(differences))
        staging.rename(target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


class ConcurrentChangeError(RuntimeError):
    pass


def metadata_signature(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def restore_held_without_overwrite(held: Path, path: Path) -> str:
    try:
        os.link(held, path, follow_symlinks=False)
        held.unlink()
        return "restored displaced file without overwriting another writer"
    except FileExistsError:
        return f"destination changed again; displaced file preserved at {held}"
    except OSError as error:
        return f"automatic restore failed; displaced file preserved at {held}: {error}"


def verify_staged_activation(
    path: Path,
    staged_identity: tuple[int, int],
    planned_bytes: bytes,
    expected_links: int,
) -> tuple[int, int, int, int, int, int]:
    """Prove that the visible path is still the staged regular file."""
    try:
        active = os.lstat(path)
    except FileNotFoundError as error:
        raise ConcurrentChangeError("activated global memory disappeared") from error
    if (
        not stat.S_ISREG(active.st_mode)
        or (active.st_dev, active.st_ino) != staged_identity
        or active.st_nlink != expected_links
        or path.read_bytes() != planned_bytes
    ):
        raise ConcurrentChangeError(
            "activated global memory was replaced, relinked, or edited concurrently"
        )
    return metadata_signature(active)


def conditional_activate(
    path: Path,
    text: str,
    previous_mode: int | None,
    expected_bytes: bytes | None,
    expected_metadata: tuple[int, int, int, int, int, int] | None,
    recovery_dir: Path,
    hold_name: str = "CLAUDE.md.pre-activation-inode",
) -> tuple[tuple[int, int, int, int, int, int], Path | None]:
    """Activate only if the path still matches preflight; never overwrite a new path."""
    descriptor, raw_temp = tempfile.mkstemp(prefix=".CLAUDE.md.", dir=path.parent)
    temporary = Path(raw_temp)
    held: Path | None = None
    planned_bytes = text.encode("utf-8")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if previous_mode is not None:
            os.chmod(temporary, stat.S_IMODE(previous_mode))
        staged_metadata = os.lstat(temporary)
        staged_identity = (staged_metadata.st_dev, staged_metadata.st_ino)
        if expected_bytes is None:
            try:
                os.link(temporary, path, follow_symlinks=False)
            except FileExistsError as error:
                raise ConcurrentChangeError(
                    "global memory appeared in the final activation window; it was not overwritten"
                ) from error
            verify_staged_activation(path, staged_identity, planned_bytes, expected_links=2)
            temporary.unlink()
            activated = verify_staged_activation(
                path, staged_identity, planned_bytes, expected_links=1
            )
            return activated, None

        if expected_metadata is None:
            raise ValueError("existing activation requires preflight metadata")
        held = recovery_dir / hold_name
        if os.path.lexists(held):
            raise FileExistsError(f"recovery hold path already exists: {held}")
        try:
            os.rename(path, held)
        except FileNotFoundError as error:
            raise ConcurrentChangeError(
                "global memory disappeared in the final activation window"
            ) from error

        held_metadata = os.lstat(held)
        held_matches = (
            stat.S_ISREG(held_metadata.st_mode)
            and metadata_signature(held_metadata) == expected_metadata
            and held.read_bytes() == expected_bytes
        )
        if not held_matches:
            restoration = restore_held_without_overwrite(held, path)
            raise ConcurrentChangeError(
                f"global memory changed in the final activation window; {restoration}"
            )

        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError as error:
            restoration = restore_held_without_overwrite(held, path)
            raise ConcurrentChangeError(
                f"another writer created global memory during activation; {restoration}"
            ) from error

        try:
            verify_staged_activation(path, staged_identity, planned_bytes, expected_links=2)
        except ConcurrentChangeError as error:
            restoration = restore_held_without_overwrite(held, path)
            raise ConcurrentChangeError(f"{error}; {restoration}") from error

        held_after = os.lstat(held)
        if (
            metadata_signature(held_after) != expected_metadata
            or held.read_bytes() != expected_bytes
        ):
            active = os.lstat(path)
            staged = os.lstat(temporary)
            if (active.st_dev, active.st_ino) == (staged.st_dev, staged.st_ino):
                path.unlink()
            restoration = restore_held_without_overwrite(held, path)
            raise ConcurrentChangeError(
                f"displaced global memory changed during activation; {restoration}"
            )
        temporary.unlink()
        try:
            activated = verify_staged_activation(
                path, staged_identity, planned_bytes, expected_links=1
            )
        except ConcurrentChangeError as error:
            restoration = restore_held_without_overwrite(held, path)
            raise ConcurrentChangeError(f"{error}; {restoration}") from error
        return activated, held
    finally:
        if temporary.exists():
            temporary.unlink()


def remove_published_stage_at(
    config_fd: int,
    transaction_fd: int,
    staged_identity: tuple[int, int],
    planned_bytes: bytes,
) -> str:
    """Remove a failed published stage without deleting another writer's inode."""
    try:
        active = os.stat("CLAUDE.md", dir_fd=config_fd, follow_symlinks=False)
    except FileNotFoundError:
        return "no staged global entry remained"
    if staged_identity != (active.st_dev, active.st_ino):
        return "global entry belongs to another writer and was preserved"
    descriptor = os.open(
        "CLAUDE.md", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=config_fd
    )
    try:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    if b"".join(chunks) == planned_bytes:
        os.unlink("CLAUDE.md", dir_fd=config_fd)
        return "failed staged global entry was removed"
    recovery = "CLAUDE.md.concurrent-active-inode"
    os.rename(
        "CLAUDE.md",
        recovery,
        src_dir_fd=config_fd,
        dst_dir_fd=transaction_fd,
    )
    return f"concurrently edited staged inode was preserved as {recovery}"


def restore_held_at(config_fd: int, transaction_fd: int, held_name: str) -> str:
    try:
        os.link(
            held_name,
            "CLAUDE.md",
            src_dir_fd=transaction_fd,
            dst_dir_fd=config_fd,
            follow_symlinks=False,
        )
        os.unlink(held_name, dir_fd=transaction_fd)
        return "preflight global memory was restored without overwrite"
    except FileExistsError:
        return f"another global entry exists; preimage remains as {held_name}"
    except OSError as error:
        return f"preimage remains as {held_name}; restore failed: {error}"


def verify_published_stage_at(
    config_fd: int,
    staged_identity: tuple[int, int],
    planned_bytes: bytes,
    expected_links: int,
) -> tuple[int, int, int, int, int, int]:
    try:
        body, active = read_regular_at(config_fd, "CLAUDE.md", expected_links=expected_links)
    except OSError as error:
        raise ConcurrentChangeError(f"published global topology changed: {error}") from error
    if staged_identity != (active.st_dev, active.st_ino) or body != planned_bytes:
        raise ConcurrentChangeError("published global memory is not the staged inode and bytes")
    return metadata_signature(active)


def conditional_activate_at(
    config_fd: int,
    transaction_fd: int,
    text: str,
    previous_mode: int | None,
    expected_bytes: bytes | None,
    expected_metadata: tuple[int, int, int, int, int, int] | None,
    hold_name: str = "CLAUDE.md.pre-activation-inode",
) -> tuple[tuple[int, int, int, int, int, int], str | None]:
    """Directory-FD anchored, no-overwrite activation."""
    planned_bytes = text.encode("utf-8")
    for _ in range(32):
        stage_name = ".CLAUDE.md." + secrets.token_hex(8)
        try:
            descriptor = os.open(
                stage_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=config_fd,
            )
            break
        except FileExistsError:
            continue
    else:
        raise OSError("could not allocate a unique activation stage")
    published = False
    displaced = False
    try:
        if previous_mode is not None:
            os.fchmod(descriptor, stat.S_IMODE(previous_mode))
        view = memoryview(planned_bytes)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
        staged_metadata = os.fstat(descriptor)
        staged_identity = (staged_metadata.st_dev, staged_metadata.st_ino)

        if expected_bytes is not None:
            if expected_metadata is None:
                raise ValueError("existing activation requires preflight metadata")
            try:
                os.rename(
                    "CLAUDE.md",
                    hold_name,
                    src_dir_fd=config_fd,
                    dst_dir_fd=transaction_fd,
                )
            except FileNotFoundError as error:
                raise ConcurrentChangeError("global memory disappeared before activation") from error
            displaced = True
            held_body, held = read_regular_at(transaction_fd, hold_name)
            if metadata_signature(held) != expected_metadata or held_body != expected_bytes:
                restoration = restore_held_at(config_fd, transaction_fd, hold_name)
                displaced = False
                raise ConcurrentChangeError(
                    f"global memory changed before activation; {restoration}"
                )

        try:
            os.link(
                stage_name,
                "CLAUDE.md",
                src_dir_fd=config_fd,
                dst_dir_fd=config_fd,
                follow_symlinks=False,
            )
        except FileExistsError as error:
            restoration = (
                restore_held_at(config_fd, transaction_fd, hold_name)
                if displaced
                else "new global entry was preserved"
            )
            displaced = False
            raise ConcurrentChangeError(
                f"another writer created global memory during activation; {restoration}"
            ) from error
        published = True
        verify_published_stage_at(config_fd, staged_identity, planned_bytes, expected_links=2)
        os.unlink(stage_name, dir_fd=config_fd)
        body, active = read_regular_at(config_fd, "CLAUDE.md", expected_links=1)
        if (active.st_dev, active.st_ino) != staged_identity or body != planned_bytes:
            raise ConcurrentChangeError("global memory changed after stage publication")
        published = False
        return metadata_signature(active), hold_name if displaced else None
    except BaseException as error:  # KeyboardInterrupt must also restore the held preimage
        cleanup = "no published stage cleanup needed"
        if published:
            try:
                cleanup = remove_published_stage_at(
                    config_fd, transaction_fd, staged_identity, planned_bytes
                )
            except OSError as cleanup_error:
                cleanup = f"published stage cleanup failed: {cleanup_error}"
        restoration = "no preimage restore needed"
        if displaced:
            restoration = restore_held_at(config_fd, transaction_fd, hold_name)
        if isinstance(error, ConcurrentChangeError):
            raise ConcurrentChangeError(f"{error}; {cleanup}; {restoration}") from error
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(stage_name, dir_fd=config_fd)
        except FileNotFoundError:
            pass


def write_activation_record_at(
    transaction_fd: int,
    activated_metadata: tuple[int, int, int, int, int, int],
    held_name: str | None,
) -> None:
    record = {
        "status": "activated",
        "completed_at": datetime.now().astimezone().isoformat(),
        "metadata": {
            "device": activated_metadata[0],
            "inode": activated_metadata[1],
            "mode": activated_metadata[2],
            "nlink": activated_metadata[3],
            "size": activated_metadata[4],
            "mtime_ns": activated_metadata[5],
        },
        "held_preimage": held_name,
    }
    write_new_file_at(
        transaction_fd,
        "activation.json",
        (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        0o600,
    )


def rollback_active_at(
    config_fd: int,
    transaction_fd: int,
    planned_bytes: bytes,
    existing_bytes: bytes | None,
    previous_mode: int | None,
    activated_metadata: tuple[int, int, int, int, int, int],
) -> str:
    try:
        if existing_bytes is not None:
            conditional_activate_at(
                config_fd,
                transaction_fd,
                existing_bytes.decode("utf-8"),
                previous_mode,
                planned_bytes,
                activated_metadata,
                hold_name="CLAUDE.md.failed-activation-inode",
            )
            return "restored the preflight global memory"
        failed_name = "CLAUDE.md.failed-activation-inode"
        os.rename(
            "CLAUDE.md",
            failed_name,
            src_dir_fd=config_fd,
            dst_dir_fd=transaction_fd,
        )
        body, metadata = read_regular_at(transaction_fd, failed_name)
        if metadata_signature(metadata) != activated_metadata or body != planned_bytes:
            restoration = restore_held_at(config_fd, transaction_fd, failed_name)
            return f"not removed because active global changed; {restoration}"
        return f"removed new global and preserved failed activation as {failed_name}"
    except (ConcurrentChangeError, OSError, UnicodeDecodeError, ValueError) as error:
        return f"rollback failed: {error}"


def rollback_global_if_unchanged(
    global_path: Path,
    planned_bytes: bytes,
    existing_bytes: bytes | None,
    previous_mode: int | None,
    activated_metadata: tuple[int, int, int, int, int, int],
    backup: Path,
) -> str:
    try:
        if existing_bytes is None:
            held = backup / "CLAUDE.md.failed-activation-inode"
            os.rename(global_path, held)
            metadata = os.lstat(held)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata_signature(metadata) != activated_metadata
                or held.read_bytes() != planned_bytes
            ):
                restoration = restore_held_without_overwrite(held, global_path)
                return f"not rolled back because global memory changed again; {restoration}"
            return f"removed the newly created global memory; preserved failed activation at {held}"
        conditional_activate(
            global_path,
            existing_bytes.decode("utf-8"),
            previous_mode,
            planned_bytes,
            activated_metadata,
            backup,
            hold_name="CLAUDE.md.failed-activation-inode",
        )
        return "restored the preflight global memory"
    except (ConcurrentChangeError, OSError, ValueError) as error:
        return f"rollback failed: {error}"


def backup_global(global_path: Path, backup_root: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    destination = backup_root / timestamp
    destination.mkdir(parents=True, exist_ok=False)
    manifest: dict[str, object] = {
        "source": str(global_path),
        "existed": global_path.is_file(),
        "created_at_local": timestamp,
    }
    if global_path.is_file():
        copied = destination / "CLAUDE.md"
        shutil.copy2(global_path, copied)
        manifest["sha256"] = digest(copied)
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--config-root", type=Path)
    parser.add_argument("--apply", action="store_true", help="perform the planned writes")
    args = parser.parse_args()

    try:
        pack = args.pack.expanduser().resolve()
        selected_config_root = (
            args.config_root if args.config_root is not None else default_config_root()
        )
        lexical_config_root = lexical_absolute(selected_config_root)
        if lexical_config_root.is_symlink():
            raise OSError(f"config root is a symlink: {lexical_config_root}")
        config_root = lexical_config_root.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        print(f"MODE: {'APPLY' if args.apply else 'PLAN (read-only)'}")
        print(f"BLOCK: command path cannot be resolved safely: {error}")
        print("RESULT: BLOCKED before writes")
        return 1
    global_path = config_root / "CLAUDE.md"
    target = config_root / "guardpack" / "versions" / VERSION
    backup_root = config_root / "guardpack" / "backups"

    problems = validate_pack(pack)
    if args.apply and args.config_root is None:
        problems.append("--apply requires an explicit --config-root copied from a reviewed PLAN")
    topology = config_topology_problems(config_root)
    problems.extend(topology)
    if topology:
        print(f"MODE: {'APPLY' if args.apply else 'PLAN (read-only)'}")
        print(f"CONFIG_ROOT: {config_root}")
        print("SETTINGS: unchanged (permissions, sandbox, hooks, model routing)")
        for problem in problems:
            print(f"BLOCK: {problem}")
        print("RESULT: BLOCKED before writes")
        return 1
    warnings: list[str] = []
    existing = ""
    existing_bytes: bytes | None = None
    previous_mode: int | None = None
    previous_metadata: tuple[int, int, int, int, int, int] | None = None
    if global_path.is_symlink():
        problems.append(f"global memory is a symlink; installer will not replace it: {global_path}")
    elif global_path.exists() and not global_path.is_file():
        problems.append(f"global memory path is not a regular file: {global_path}")
    elif global_path.is_file():
        try:
            metadata = global_path.stat()
            if metadata.st_nlink > 1:
                raise ValueError("global memory is a hard link; installer will not replace it")
            existing_bytes = global_path.read_bytes()
            existing = existing_bytes.decode("utf-8")
            previous_mode = metadata.st_mode
            previous_metadata = metadata_signature(metadata)
            marker_positions(existing)
        except (OSError, UnicodeDecodeError, ValueError) as error:
            problems.append(f"global memory preflight failed: {error}")

    conflict_problems, conflict_warnings = known_conflicts(
        global_path if global_path.is_file() else None, config_root / "rules"
    )
    problems.extend(conflict_problems)
    warnings.extend(conflict_warnings)
    warnings.extend(scan_routing_candidates(config_root, pack))

    target_state = "absent"
    if target.is_symlink():
        problems.append(f"version target is a symlink; installer will not use it: {target}")
        target_state = "invalid"
    elif target.exists():
        if not target.is_dir():
            problems.append(f"version target exists but is not a directory: {target}")
            target_state = "invalid"
        else:
            differences = compare_installed(pack, target)
            if differences:
                problems.extend(differences)
                target_state = "different; will not overwrite"
            else:
                target_state = "identical; reuse"

    print(f"MODE: {'APPLY' if args.apply else 'PLAN (read-only)'}")
    print(f"CONFIG_ROOT: {config_root}")
    print(f"GLOBAL_MEMORY: {global_path} ({'exists' if global_path.is_file() else 'new'})")
    print(f"VERSION_TARGET: {target} ({target_state})")
    print("SETTINGS: unchanged (permissions, sandbox, hooks, model routing)")
    for warning in warnings:
        print(f"WARN: {warning}")
    print("WARN: project/local/managed/auto memory and arbitrary semantic conflicts need separate audit")
    if problems:
        for problem in problems:
            print(f"BLOCK: {problem}")
        print("RESULT: BLOCKED before writes")
        return 1
    planned_text = planned_global_text(existing)
    planned_bytes = planned_text.encode("utf-8")
    already_installed = (
        target_state == "identical; reuse"
        and existing_bytes is not None
        and existing_bytes == planned_bytes
    )
    if already_installed:
        print("RESULT: ALREADY_INSTALLED_NO_WRITES")
        return 0
    if not args.apply:
        print(
            f"PLAN: back up the current global memory, install/reuse v{VERSION}, "
            "update only the marker block"
        )
        next_apply = shlex.join(
            [
                sys.executable,
                "-B",
                str(Path(__file__).resolve()),
                "--pack",
                str(pack),
                "--config-root",
                str(config_root),
                "--apply",
            ]
        )
        print(f"NEXT_APPLY: {next_apply}")
        print("RESULT: NO WRITES; rerun with --apply after reviewing this plan")
        return 0

    config_fd = guardpack_fd = versions_fd = backups_fd = transaction_fd = version_fd = -1
    backup: Path | None = None
    activated_metadata: tuple[int, int, int, int, int, int] | None = None
    held_preimage: str | None = None
    try:
        snapshot = read_source_snapshot(pack)
        config_fd = open_physical_directory(config_root, create=True)

        try:
            anchored_bytes, anchored = read_regular_at(config_fd, "CLAUDE.md")
        except FileNotFoundError:
            anchored_bytes, anchored = None, None
        if existing_bytes is None:
            if anchored_bytes is not None:
                raise ConcurrentChangeError("global memory appeared after preflight")
        elif (
            anchored_bytes != existing_bytes
            or anchored is None
            or metadata_signature(anchored) != previous_metadata
        ):
            raise ConcurrentChangeError("global memory changed after preflight")

        guardpack_fd = open_child_directory(config_fd, "guardpack", create=True)
        versions_fd = open_child_directory(guardpack_fd, "versions", create=True)
        backups_fd = open_child_directory(guardpack_fd, "backups", create=True, private=True)
        assert_managed_tree(
            config_root, config_fd, guardpack_fd, versions_fd, backups_fd
        )
        backup, transaction_fd = secure_backup_at(
            backups_fd, config_root, existing_bytes, previous_mode, planned_bytes
        )
        version_fd, _ = open_or_install_version(versions_fd, snapshot)
        assert_managed_tree(
            config_root, config_fd, guardpack_fd, versions_fd, backups_fd, version_fd
        )
        activated_metadata, held_preimage = conditional_activate_at(
            config_fd,
            transaction_fd,
            planned_text,
            previous_mode,
            existing_bytes,
            previous_metadata,
        )
        differences = verify_version_at(version_fd, snapshot)
        try:
            assert_managed_tree(
                config_root, config_fd, guardpack_fd, versions_fd, backups_fd, version_fd
            )
        except ConcurrentChangeError as error:
            differences.append(str(error))
        if differences:
            rollback = rollback_active_at(
                config_fd,
                transaction_fd,
                planned_bytes,
                existing_bytes,
                previous_mode,
                activated_metadata,
            )
            raise OSError(
                "post-activation version verification failed: "
                + "; ".join(differences)
                + f"; rollback: {rollback}"
            )
        write_activation_record_at(transaction_fd, activated_metadata, held_preimage)
    except (ConcurrentChangeError, OSError, UnicodeDecodeError, ValueError) as error:
        print(f"ERROR: anchored installation failed: {error}")
        if backup is not None:
            print(f"BACKUP: {backup}")
        return 1
    finally:
        for descriptor in (
            version_fd, transaction_fd, backups_fd, versions_fd, guardpack_fd, config_fd
        ):
            if descriptor >= 0:
                os.close(descriptor)

    assert backup is not None and activated_metadata is not None
    print(f"BACKUP: {backup}")
    if held_preimage is not None:
        print(f"HELD_PREIMAGE: {backup / held_preimage}")
    print("RESULT: INSTALLED; start a new supported local Claude Code session and verify loaded memory")
    print("NOTE: Cowork can skip user-scope imports that resolve outside its working directory")
    return 0


if __name__ == "__main__":
    sys.exit(main())
