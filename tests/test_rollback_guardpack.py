#!/usr/bin/env python3
"""Regression tests for explicit, conditional user-memory rollback."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PACK = Path(__file__).resolve().parents[1]
INSTALL = PACK / "install_guardpack.py"
ROLLBACK = PACK / "rollback_guardpack.py"


class RollbackGuardpackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="guardpack-rollback-test-")
        self.root = Path(self.temp.name) / "config"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_command(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(command, text=True, capture_output=True, env=environment)

    def install(self) -> Path:
        result = self.run_command(
            [
                sys.executable, "-B", str(INSTALL), "--pack", str(PACK),
                "--config-root", str(self.root), "--apply",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        backups = sorted((self.root / "guardpack/backups").glob("*/manifest.json"))
        self.assertEqual(len(backups), 1)
        return backups[0].parent

    def rollback(self, backup: Path, apply: bool = False) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable, "-B", str(ROLLBACK), "--backup", str(backup),
            "--config-root", str(self.root),
        ]
        if apply:
            command.append("--apply")
        return self.run_command(command)

    def test_plan_is_read_only_and_outputs_exact_next_command(self) -> None:
        self.root.mkdir(parents=True)
        original = b"# original  \n\n"
        (self.root / "CLAUDE.md").write_bytes(original)
        backup = self.install()
        active = (self.root / "CLAUDE.md").read_bytes()
        backups_before = sorted(path.name for path in (self.root / "guardpack/backups").iterdir())
        result = self.rollback(backup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("NEXT_ROLLBACK:", result.stdout)
        self.assertIn("RESULT: NO WRITES", result.stdout)
        self.assertEqual((self.root / "CLAUDE.md").read_bytes(), active)
        self.assertEqual(
            backups_before,
            sorted(path.name for path in (self.root / "guardpack/backups").iterdir()),
        )

    def test_existing_global_is_restored_byte_for_byte(self) -> None:
        self.root.mkdir(parents=True)
        original = b"# original hard break  \n\n\n"
        global_path = self.root / "CLAUDE.md"
        global_path.write_bytes(original)
        os.chmod(global_path, 0o640)
        backup = self.install()
        result = self.rollback(backup, apply=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ROLLED_BACK_USER_MEMORY_FULL", result.stdout)
        self.assertEqual(global_path.read_bytes(), original)
        self.assertEqual(global_path.stat().st_mode & 0o777, 0o640)
        self.assertTrue((self.root / "guardpack/versions/2.3.7").is_dir())

    def test_new_global_is_removed_but_version_is_left(self) -> None:
        backup = self.install()
        result = self.rollback(backup, apply=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ROLLED_BACK_USER_MEMORY_REMOVED_NEW_FILE", result.stdout)
        self.assertFalse((self.root / "CLAUDE.md").exists())
        self.assertTrue((self.root / "guardpack/versions/2.3.7").is_dir())

    def test_upgrade_rollback_restores_previous_marker_and_keeps_both_trees(self) -> None:
        for previous in ("2.2.0", "2.3.0", "2.3.1", "2.3.2"):
            with self.subTest(previous=previous):
                self.root = Path(self.temp.name) / f"config-{previous}"
                old_target = self.root / f"guardpack/versions/{previous}"
                old_target.mkdir(parents=True)
                shutil.copy2(
                    PACK / "00-글로벌-코어.md",
                    old_target / "00-글로벌-코어.md",
                )
                original = (
                    "# personal before upgrade\n\n"
                    "<!-- VIBECODING_GUARDPACK_BEGIN -->\n"
                    f"@guardpack/versions/{previous}/00-글로벌-코어.md\n"
                    "<!-- VIBECODING_GUARDPACK_END -->\n"
                ).encode("utf-8")
                global_path = self.root / "CLAUDE.md"
                global_path.write_bytes(original)

                backup = self.install()
                active = global_path.read_text(encoding="utf-8")
                self.assertIn("@guardpack/versions/2.3.7/00-글로벌-코어.md", active)

                result = self.rollback(backup, apply=True)

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(global_path.read_bytes(), original)
                self.assertTrue((self.root / f"guardpack/versions/{previous}").is_dir())
                self.assertTrue((self.root / "guardpack/versions/2.3.7").is_dir())

    def test_changed_global_blocks_without_overwrite(self) -> None:
        backup = self.install()
        changed = b"# user edit after installation\n"
        (self.root / "CLAUDE.md").write_bytes(changed)
        result = self.rollback(backup, apply=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no longer exactly matches", result.stdout)
        self.assertEqual((self.root / "CLAUDE.md").read_bytes(), changed)

    def test_apply_without_explicit_config_root_blocks(self) -> None:
        backup = self.install()
        environment = os.environ.copy()
        environment["CLAUDE_CONFIG_DIR"] = str(self.root)
        result = subprocess.run(
            [sys.executable, "-B", str(ROLLBACK), "--backup", str(backup), "--apply"],
            text=True,
            capture_output=True,
            env=environment,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires an explicit --config-root", result.stdout)

    def test_tampered_manifest_or_symlink_is_rejected(self) -> None:
        for kind in ("tamper", "symlink"):
            with self.subTest(kind=kind):
                case_root = Path(self.temp.name) / ("config-" + kind)
                self.root = case_root
                backup = self.install()
                manifest = backup / "manifest.json"
                if kind == "tamper":
                    value = json.loads(manifest.read_text(encoding="utf-8"))
                    value["expected_activation"]["sha256"] = "0" * 64
                    manifest.write_text(json.dumps(value) + "\n", encoding="utf-8")
                else:
                    peer = backup / "manifest-peer.json"
                    peer.write_bytes(manifest.read_bytes())
                    manifest.unlink()
                    manifest.symlink_to(peer)
                result = self.rollback(backup, apply=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("RESULT: BLOCKED", result.stdout)

    def test_v22_backup_contract_is_not_misapplied_by_v23_rollback(self) -> None:
        backup = self.install()
        manifest = backup / "manifest.json"
        value = json.loads(manifest.read_text(encoding="utf-8"))
        value["guardpack_version"] = "2.2.0"
        manifest.write_text(json.dumps(value) + "\n", encoding="utf-8")

        result = self.rollback(backup, apply=True)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not match v2.3.7", result.stdout)
        self.assertIn("RESULT: BLOCKED", result.stdout)

    def test_interrupted_activation_without_record_is_recovered_from_preimage(self) -> None:
        # AUD-FS-01/02/04: activation.json missing after Ctrl-C / link failure / disk full.
        for kind in ("vanished", "activated_but_unrecorded"):
            with self.subTest(kind=kind):
                self.root = Path(self.temp.name) / ("config-" + kind)
                self.root.mkdir(parents=True)
                original = b"# original rules\n- keep\n"
                global_path = self.root / "CLAUDE.md"
                global_path.write_bytes(original)
                backup = self.install()
                (backup / "activation.json").unlink()
                if kind == "vanished":
                    global_path.unlink()  # what FS-01/FS-02 leave behind in the config root
                result = self.rollback(backup, apply=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("activation.json is missing", result.stdout)
                self.assertIn("ROLLED_BACK_USER_MEMORY_FULL", result.stdout)
                self.assertEqual(global_path.read_bytes(), original)

    def test_unrecorded_activation_with_foreign_global_is_blocked(self) -> None:
        self.root.mkdir(parents=True)
        (self.root / "CLAUDE.md").write_bytes(b"# original\n")
        backup = self.install()
        (backup / "activation.json").unlink()
        (self.root / "CLAUDE.md").write_bytes(b"# edited by user after the interrupted install\n")
        result = self.rollback(backup, apply=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("activation was never recorded", result.stdout)
        self.assertIn("RESULT: BLOCKED", result.stdout)
        self.assertEqual((self.root / "CLAUDE.md").read_bytes(), b"# edited by user after the interrupted install\n")

    def test_second_rollback_is_no_write(self) -> None:
        backup = self.install()
        first = self.rollback(backup, apply=True)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        second = self.rollback(backup, apply=True)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("ALREADY_ROLLED_BACK_NO_WRITES", second.stdout)


if __name__ == "__main__":
    unittest.main()
