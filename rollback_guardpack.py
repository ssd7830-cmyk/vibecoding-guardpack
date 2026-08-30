#!/usr/bin/env python3
"""Conditionally restore user CLAUDE.md from one explicit current-version backup."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shlex
import stat
import sys
from datetime import datetime
from pathlib import Path

from install_guardpack import (
    ConcurrentChangeError,
    VERSION,
    assert_directory_entry,
    assert_config_root_entry,
    conditional_activate_at,
    default_config_root,
    directory_flags,
    lexical_absolute,
    metadata_signature,
    open_child_directory,
    open_physical_directory,
    read_regular_at,
    restore_held_at,
    write_new_file_at,
)
from verify_guardpack import strict_json_loads


def read_json_at(parent_fd: int, name: str) -> dict[str, object]:
    body, _ = read_regular_at(parent_fd, name)
    try:
        value = strict_json_loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError(f"invalid {name}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{name} must contain one JSON object")
    return value


def create_recovery_transaction(
    backups_fd: int, config_root: Path, source_backup: Path, active_bytes: bytes | None
) -> tuple[Path, int]:
    for _ in range(32):
        leaf = "rollback-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f-") + secrets.token_hex(4)
        try:
            os.mkdir(leaf, 0o700, dir_fd=backups_fd)
            break
        except FileExistsError:
            continue
    else:
        raise OSError("could not allocate rollback recovery transaction")
    transaction_fd = open_child_directory(backups_fd, leaf, create=False, private=True)
    if active_bytes is not None:
        write_new_file_at(transaction_fd, "CLAUDE.md.active-before-rollback", active_bytes, 0o600)
    record = {
        "schema_version": 1,
        "status": "prepared",
        "config_root": str(config_root),
        "source_backup": str(source_backup),
        "active_sha256": hashlib.sha256(active_bytes).hexdigest() if active_bytes is not None else None,
        "created_at": datetime.now().astimezone().isoformat(),
    }
    write_new_file_at(
        transaction_fd,
        "rollback-manifest.json",
        (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        0o600,
    )
    return config_root / "guardpack" / "backups" / leaf, transaction_fd


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--config-root", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    try:
        selected = args.config_root if args.config_root is not None else default_config_root()
        lexical_root = lexical_absolute(selected)
        if lexical_root.is_symlink():
            raise OSError(f"config root is a symlink: {lexical_root}")
        config_root = lexical_root.resolve(strict=False)
        if args.apply and args.config_root is None:
            raise ValueError("--apply requires an explicit --config-root copied from PLAN")
        lexical_backup = lexical_absolute(args.backup)
        if lexical_backup.is_symlink():
            raise OSError(f"backup transaction is a symlink: {lexical_backup}")
        backup_path = lexical_backup.resolve(strict=False)
        expected_parent = config_root / "guardpack" / "backups"
        if backup_path.parent != expected_parent or backup_path.name in ("", ".", ".."):
            raise ValueError("backup must be one explicit direct child of this config root's backups")
    except (OSError, RuntimeError, ValueError) as error:
        print(f"MODE: {'APPLY' if args.apply else 'PLAN (read-only)'}")
        print(f"BLOCK: {error}")
        print("RESULT: BLOCKED_NO_WRITES")
        return 1

    descriptors: list[int] = []
    recovery_fd = -1
    recovery_path: Path | None = None
    try:
        config_fd = open_physical_directory(config_root, create=False)
        descriptors.append(config_fd)
        guardpack_fd = open_child_directory(config_fd, "guardpack", create=False)
        descriptors.append(guardpack_fd)
        versions_fd = open_child_directory(guardpack_fd, "versions", create=False)
        descriptors.append(versions_fd)
        backups_fd = open_child_directory(guardpack_fd, "backups", create=False)
        descriptors.append(backups_fd)
        backup_fd = open_child_directory(backups_fd, backup_path.name, create=False, private=True)
        descriptors.append(backup_fd)
        assert_config_root_entry(config_root, config_fd)
        assert_directory_entry(config_fd, "guardpack", guardpack_fd)
        assert_directory_entry(guardpack_fd, "versions", versions_fd)
        assert_directory_entry(guardpack_fd, "backups", backups_fd)
        assert_directory_entry(backups_fd, backup_path.name, backup_fd)

        manifest = read_json_at(backup_fd, "manifest.json")
        try:
            activation: dict[str, object] | None = read_json_at(backup_fd, "activation.json")
        except FileNotFoundError:
            # AUD-FS-01/02/04: the installer was interrupted (Ctrl-C, link-unsupported
            # filesystem, disk full) after moving the preimage aside but before recording
            # the activation. The backup still holds the exact preimage, so allow recovery.
            activation = None
        preimage = manifest.get("preimage")
        expected = manifest.get("expected_activation")
        if (
            manifest.get("schema_version") != 2
            or manifest.get("guardpack_version") != VERSION
            or manifest.get("config_root") != str(config_root)
            or not isinstance(preimage, dict)
            or not isinstance(expected, dict)
            or (activation is not None and activation.get("status") != "activated")
        ):
            raise ValueError(
                f"backup manifest/activation contract does not match v{VERSION}"
            )
        preimage_existed = preimage.get("existed") is True
        preimage_hash = preimage.get("sha256")
        preimage_size = preimage.get("size")
        preimage_mode = preimage.get("mode")
        active_hash = expected.get("sha256")
        active_size = expected.get("size")
        if not all(
            isinstance(value, str) and len(value) == 64
            for value in (preimage_hash, active_hash)
        ) or not all(isinstance(value, int) and value >= 0 for value in (preimage_size, active_size)):
            raise ValueError("backup manifest hashes/sizes are malformed")
        if preimage_existed:
            preimage_bytes, _ = read_regular_at(backup_fd, "CLAUDE.md")
            if (
                hashlib.sha256(preimage_bytes).hexdigest() != preimage_hash
                or len(preimage_bytes) != preimage_size
                or not isinstance(preimage_mode, int)
            ):
                raise ValueError("backup preimage does not match its manifest")
            preimage_bytes.decode("utf-8")
        else:
            preimage_bytes = None

        try:
            current_bytes, current_metadata_raw = read_regular_at(config_fd, "CLAUDE.md")
            current_metadata = metadata_signature(current_metadata_raw)
        except FileNotFoundError:
            current_bytes, current_metadata = None, None
        already = (
            (not preimage_existed and current_bytes is None)
            or (preimage_existed and current_bytes == preimage_bytes)
        )
        active_matches = (
            current_bytes is not None
            and hashlib.sha256(current_bytes).hexdigest() == active_hash
            and len(current_bytes) == active_size
        )
        if already:
            print(f"MODE: {'APPLY' if args.apply else 'PLAN (read-only)'}")
            print("RESULT: ALREADY_ROLLED_BACK_NO_WRITES")
            return 0
        if activation is None:
            if current_bytes is not None and not active_matches:
                raise ConcurrentChangeError(
                    "activation was never recorded and the current global memory matches "
                    "neither this backup's planned activation nor its preimage"
                )
            print("NOTE: activation.json is missing; recovering an interrupted activation from the backup preimage")
        elif not active_matches or current_metadata is None:
            raise ConcurrentChangeError(
                "current global memory no longer exactly matches this backup's activation"
            )

        print(f"MODE: {'APPLY' if args.apply else 'PLAN (read-only)'}")
        print(f"CONFIG_ROOT: {config_root}")
        print(f"BACKUP: {backup_path}")
        print("SCOPE: user CLAUDE.md only; version directory and settings remain unchanged")
        if not args.apply:
            command = shlex.join(
                [
                    sys.executable,
                    "-B",
                    str(Path(__file__).resolve()),
                    "--backup",
                    str(backup_path),
                    "--config-root",
                    str(config_root),
                    "--apply",
                ]
            )
            print(f"NEXT_ROLLBACK: {command}")
            print("RESULT: NO WRITES; reviewed rollback is ready")
            return 0

        recovery_path, recovery_fd = create_recovery_transaction(
            backups_fd, config_root, backup_path, current_bytes
        )
        if preimage_existed:
            assert preimage_bytes is not None
            conditional_activate_at(
                config_fd,
                recovery_fd,
                preimage_bytes.decode("utf-8"),
                preimage_mode,
                current_bytes,
                current_metadata,
                hold_name="CLAUDE.md.rollback-active-inode",
            )
            final, _ = read_regular_at(config_fd, "CLAUDE.md")
            if final != preimage_bytes:
                raise ConcurrentChangeError("rollback postcondition does not match preimage")
            result_name = "ROLLED_BACK_USER_MEMORY_FULL"
        else:
            assert current_bytes is not None  # otherwise `already` returned above
            held = "CLAUDE.md.rollback-active-inode"
            os.rename("CLAUDE.md", held, src_dir_fd=config_fd, dst_dir_fd=recovery_fd)
            moved, moved_metadata = read_regular_at(recovery_fd, held)
            if moved != current_bytes or metadata_signature(moved_metadata) != current_metadata:
                restoration = restore_held_at(config_fd, recovery_fd, held)
                raise ConcurrentChangeError(f"active global changed during rollback; {restoration}")
            try:
                os.stat("CLAUDE.md", dir_fd=config_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise ConcurrentChangeError("global memory reappeared during rollback")
            result_name = "ROLLED_BACK_USER_MEMORY_REMOVED_NEW_FILE"
        write_new_file_at(
            recovery_fd,
            "rollback-result.json",
            (json.dumps({"status": result_name, "completed_at": datetime.now().astimezone().isoformat()}) + "\n").encode("utf-8"),
            0o600,
        )
        print(f"RECOVERY: {recovery_path}")
        print(f"RESULT: {result_name}")
        print("LEFT_IN_PLACE: guardpack version directory and all settings")
        print("NOT_RESTORED: manual migration edits, project/managed/auto memory, external state")
        return 0
    except (ConcurrentChangeError, FileNotFoundError, OSError, UnicodeDecodeError, ValueError) as error:
        print(f"MODE: {'APPLY' if args.apply else 'PLAN (read-only)'}")
        print(f"BLOCK: {error}")
        if recovery_path is not None:
            print(f"RECOVERY: {recovery_path}")
        print("RESULT: BLOCKED_NO_WRITES_OR_NO_OVERWRITE")
        return 1
    finally:
        if recovery_fd >= 0:
            os.close(recovery_fd)
        for descriptor in reversed(descriptors):
            os.close(descriptor)


if __name__ == "__main__":
    sys.exit(main())
