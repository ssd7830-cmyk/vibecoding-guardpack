#!/usr/bin/env python3
"""Regression tests for the conservative guardpack installer."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock


PACK = Path(__file__).resolve().parents[1]
INSTALL = PACK / "install_guardpack.py"
sys.path.insert(0, str(PACK))

import install_guardpack as installer  # noqa: E402


V23_DISTRIBUTION_FILES = {
    ".claude-plugin/marketplace.json",
    ".claude-plugin/plugin.json",
    "docs/QUICKSTART.md",
    "docs/EVALUATION.md",
    "docs/MAINTAINERS.md",
    "skills/guardpack-safety-audit/SKILL.md",
    "skills/guardpack-completion-check/SKILL.md",
    "skills/guardpack-debug-evidence/SKILL.md",
    "skills/guardpack-context-intent/SKILL.md",
    "skills/guardpack-evidence-review/SKILL.md",
    "skills/guardpack/SKILL.md",
    "tests/test_skills_contract.py",
}


class InstallGuardpackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="guardpack-installer-test-")
        self.root = Path(self.temp.name) / "config"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_install(self, apply: bool = False, pack: Path = PACK) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            "-B",
            str(pack / "install_guardpack.py"),
            "--pack",
            str(pack),
            "--config-root",
            str(self.root),
        ]
        if apply:
            command.append("--apply")
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(command, text=True, capture_output=True, env=environment)

    def test_plan_is_read_only(self) -> None:
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("RESULT: NO WRITES", result.stdout)
        self.assertIn(f"--config-root {self.root.resolve()}", result.stdout)
        self.assertFalse(self.root.exists())

    def make_audit_skill(self) -> Path:
        skill = self.root / "skills" / "audit" / "SKILL.md"
        skill.parent.mkdir(parents=True, exist_ok=True)
        skill.write_text(
            "---\n"
            "name: audit\n"
            "description: 프로젝트 견고성 감사와 적대 검증\n"
            "---\n\n# audit\n",
            encoding="utf-8",
        )
        return skill

    def test_plan_reports_routing_candidate_without_writes_or_block(self) -> None:
        skill = self.make_audit_skill()
        before = skill.read_bytes()

        result = self.run_install()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("WARN: ROUTING-POLICY: audit", result.stdout)
        self.assertNotIn("BLOCK:", result.stdout)
        self.assertIn("RESULT: NO WRITES", result.stdout)
        self.assertEqual(skill.read_bytes(), before)
        self.assertFalse((self.root / "CLAUDE.md").exists())
        self.assertFalse((self.root / "guardpack").exists())

    def test_apply_routing_warning_does_not_block_install(self) -> None:
        self.make_audit_skill()

        result = self.run_install(apply=True)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("WARN: ROUTING-POLICY: audit", result.stdout)
        self.assertNotIn("BLOCK:", result.stdout)
        self.assertTrue((self.root / "CLAUDE.md").is_file())

    def test_nul_plugin_path_is_warn_only_for_installer_plan(self) -> None:
        inventory = self.root / "plugins" / "installed_plugins.json"
        inventory.parent.mkdir(parents=True)
        inventory.write_text(
            json.dumps(
                {
                    "version": 2,
                    "plugins": {
                        "bad@official": [
                            {
                                "scope": "user",
                                "installPath": str(self.root / "plugins" / "bad") + "\u0000tail",
                            }
                        ]
                    },
                }
            ),
            encoding="utf-8",
        )

        result = self.run_install()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("WARN: ROUTING-SCAN-INCOMPLETE:", result.stdout)
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        self.assertNotIn("BLOCK:", result.stdout)
        self.assertIn("RESULT: NO WRITES", result.stdout)

    def test_apply_without_explicit_config_root_is_refused(self) -> None:
        command = [sys.executable, "-B", str(INSTALL), "--pack", str(PACK), "--apply"]
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["CLAUDE_CONFIG_DIR"] = str(self.root)
        result = subprocess.run(command, text=True, capture_output=True, env=environment)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires an explicit --config-root", result.stdout)
        self.assertFalse(self.root.exists())

    def test_fresh_apply_installs_and_backs_up_missing_state(self) -> None:
        result = self.run_install(apply=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        global_text = (self.root / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertEqual(global_text.count("VIBECODING_GUARDPACK_BEGIN"), 1)
        self.assertIn("@guardpack/versions/2.3.7/00-글로벌-코어.md", global_text)
        installed = self.root / "guardpack/versions/2.3.7"
        self.assertTrue((installed / "README.md").is_file())
        for relative in installer.REQUIRED:
            with self.subTest(relative=relative):
                self.assertEqual(
                    (installed / relative).read_bytes(),
                    (PACK / relative).read_bytes(),
                )
        manifests = list((self.root / "guardpack/backups").glob("*/manifest.json"))
        self.assertEqual(len(manifests), 1)
        manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
        self.assertIs(manifest["preimage"]["existed"], False)
        self.assertEqual(manifest["guardpack_version"], "2.3.7")
        self.assertEqual(
            manifest["expected_activation"]["managed_import"],
            "@guardpack/versions/2.3.7/00-글로벌-코어.md",
        )

    def test_v23_distribution_files_are_closed_manifest_members(self) -> None:
        self.assertTrue(V23_DISTRIBUTION_FILES.issubset(set(installer.REQUIRED)))

        candidate = self.root.parent / "pack-missing-v23-file"
        shutil.copytree(PACK, candidate)
        for relative in sorted(V23_DISTRIBUTION_FILES):
            with self.subTest(relative=relative):
                path = candidate / relative
                body = path.read_bytes()
                path.unlink()
                self.assertIn(
                    f"package file missing: {relative}",
                    installer.validate_pack(candidate),
                )
                path.write_bytes(body)

    def test_apply_upgrades_managed_previous_import_without_removing_old_tree(self) -> None:
        for previous in ("2.2.0", "2.3.0", "2.3.1", "2.3.2"):
            with self.subTest(previous=previous):
                self.root = Path(self.temp.name) / f"config-{previous}"
                old_target = self.root / f"guardpack/versions/{previous}"
                old_target.mkdir(parents=True)
                old_core = old_target / "00-글로벌-코어.md"
                shutil.copy2(PACK / "00-글로벌-코어.md", old_core)
                old_core_hash = installer.digest(old_core)
                global_path = self.root / "CLAUDE.md"
                old_import = f"@guardpack/versions/{previous}/00-글로벌-코어.md"
                global_path.write_text(
                    "# personal\n\n"
                    "<!-- VIBECODING_GUARDPACK_BEGIN -->\n"
                    f"{old_import}\n"
                    "<!-- VIBECODING_GUARDPACK_END -->\n",
                    encoding="utf-8",
                )

                result = self.run_install(apply=True)

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                updated = global_path.read_text(encoding="utf-8")
                self.assertIn("@guardpack/versions/2.3.7/00-글로벌-코어.md", updated)
                self.assertNotIn(old_import, updated)
                self.assertEqual(installer.digest(old_core), old_core_hash)
                self.assertTrue((self.root / "guardpack/versions/2.3.7").is_dir())

    def test_upgrade_preserves_user_content_before_and_after_marker_block(self) -> None:
        # AUD-TST-01: a prefix-dropping mutation of planned_global_text survived the suite.
        self.root.mkdir(parents=True)
        old_target = self.root / "guardpack/versions/2.3.2"
        old_target.mkdir(parents=True)
        shutil.copy2(PACK / "00-글로벌-코어.md", old_target / "00-글로벌-코어.md")
        prefix = "# 내 규칙 (앞)\n- keep me\n\n"
        suffix = "\n\n# 내 규칙 (뒤)\n- keep me too\n"
        old_block = (
            "<!-- VIBECODING_GUARDPACK_BEGIN -->\n"
            "@guardpack/versions/2.3.2/00-글로벌-코어.md\n"
            "<!-- VIBECODING_GUARDPACK_END -->"
        )
        global_path = self.root / "CLAUDE.md"
        global_path.write_bytes((prefix + old_block + suffix).encode("utf-8"))

        result = self.run_install(apply=True)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            global_path.read_bytes(),
            (prefix + installer.managed_block() + suffix).encode("utf-8"),
        )

    def test_tampered_v23_skill_blocks_reuse_before_global_write(self) -> None:
        first = self.run_install(apply=True)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        global_path = self.root / "CLAUDE.md"
        before = global_path.read_bytes()
        target = (
            self.root
            / "guardpack/versions/2.3.7/skills/guardpack-safety-audit/SKILL.md"
        )
        target.write_text("tampered\n", encoding="utf-8")

        second = self.run_install(apply=True)

        self.assertNotEqual(second.returncode, 0)
        self.assertIn("installed hash differs: skills/guardpack-safety-audit/SKILL.md", second.stdout)
        self.assertEqual(global_path.read_bytes(), before)

    def test_existing_user_content_is_preserved(self) -> None:
        self.root.mkdir(parents=True)
        (self.root / "CLAUDE.md").write_text("# personal\nKeep this.\n", encoding="utf-8")
        result = self.run_install(apply=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        updated = (self.root / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertTrue(updated.startswith("# personal\nKeep this.\n"))

    def test_existing_eof_whitespace_is_preserved_byte_for_byte(self) -> None:
        self.root.mkdir(parents=True)
        existing = b"# personal hard break  \n\n\n"
        (self.root / "CLAUDE.md").write_bytes(existing)
        result = self.run_install(apply=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        updated = (self.root / "CLAUDE.md").read_bytes()
        self.assertTrue(updated.startswith(existing))
        self.assertIn(b"VIBECODING_GUARDPACK_BEGIN", updated[len(existing):])

    def test_second_apply_reuses_identical_version(self) -> None:
        first = self.run_install(apply=True)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        backups_before = list((self.root / "guardpack/backups").iterdir())
        second = self.run_install(apply=True)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("identical; reuse", second.stdout)
        self.assertIn("ALREADY_INSTALLED_NO_WRITES", second.stdout)
        self.assertEqual(
            sorted(path.name for path in backups_before),
            sorted(path.name for path in (self.root / "guardpack/backups").iterdir()),
        )

    def test_existing_different_version_is_never_overwritten(self) -> None:
        target = self.root / "guardpack/versions/2.3.7"
        target.mkdir(parents=True)
        sentinel = target / "README.md"
        sentinel.write_text("different\n", encoding="utf-8")
        result = self.run_install(apply=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RESULT: BLOCKED before writes", result.stdout)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "different\n")
        self.assertFalse((self.root / "CLAUDE.md").exists())

    def test_known_legacy_conflict_blocks_before_writes(self) -> None:
        self.root.mkdir(parents=True)
        global_path = self.root / "CLAUDE.md"
        legacy = self.root / "legacy.md"
        global_path.write_text("- old policy: @legacy.md\n", encoding="utf-8")
        legacy.write_text(
            "실패한 수정을 전부 원복한다 — 원인 불명 변경이 얹힌 코드로는 진단이 오염된다.\n",
            encoding="utf-8",
        )
        before = global_path.read_bytes()
        result = self.run_install(apply=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("legacy fingerprint candidate 'blanket rollback'", result.stdout)
        self.assertEqual(global_path.read_bytes(), before)
        self.assertFalse((self.root / "guardpack/versions/2.3.7").exists())

    def test_unscoped_user_rule_conflict_blocks_before_writes(self) -> None:
        rules = self.root / "rules"
        rules.mkdir(parents=True)
        (rules / "legacy.md").write_text(
            "실패한 수정을 전부 원복한다 — 원인 불명 변경이 얹힌 코드로는 진단이 오염된다.\n",
            encoding="utf-8",
        )
        result = self.run_install(apply=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("legacy fingerprint candidate 'blanket rollback'", result.stdout)
        self.assertFalse((self.root / "CLAUDE.md").exists())
        self.assertFalse((self.root / "guardpack/versions/2.3.7").exists())

    def test_nested_or_scalar_paths_text_does_not_exempt_user_rule(self) -> None:
        rules = self.root / "rules"
        rules.mkdir(parents=True)
        conflict = (
            "실패한 수정을 전부 원복한다 — 원인 불명 변경이 얹힌 코드로는 진단이 오염된다.\n"
        )
        for frontmatter in (
            "---\nmetadata:\n  paths: [\"src/**\"]\n---\n",
            "---\nnote: |\n  paths: [\"src/**\"]\n---\n",
        ):
            with self.subTest(frontmatter=frontmatter):
                (rules / "legacy.md").write_text(frontmatter + conflict, encoding="utf-8")
                result = self.run_install(apply=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("legacy fingerprint candidate 'blanket rollback'", result.stdout)
                self.assertFalse((self.root / "CLAUDE.md").exists())

    def test_reversed_markers_block_before_writes(self) -> None:
        self.root.mkdir(parents=True)
        global_path = self.root / "CLAUDE.md"
        global_path.write_text(
            "<!-- VIBECODING_GUARDPACK_END -->\n"
            "@guardpack/versions/2.1.0/00-글로벌-코어.md\n"
            "<!-- VIBECODING_GUARDPACK_BEGIN -->\n",
            encoding="utf-8",
        )
        before = global_path.read_bytes()
        result = self.run_install(apply=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("managed markers are reversed", result.stdout)
        self.assertEqual(global_path.read_bytes(), before)

    def test_unrelated_content_inside_managed_block_is_preserved_by_refusal(self) -> None:
        self.root.mkdir(parents=True)
        global_path = self.root / "CLAUDE.md"
        global_path.write_text(
            "<!-- VIBECODING_GUARDPACK_BEGIN -->\n"
            "@guardpack/versions/2.1.0/00-글로벌-코어.md\n"
            "Keep this unrelated rule.\n"
            "<!-- VIBECODING_GUARDPACK_END -->\n",
            encoding="utf-8",
        )
        before = global_path.read_bytes()
        result = self.run_install(apply=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("content other than one guardpack core import", result.stdout)
        self.assertEqual(global_path.read_bytes(), before)

    def test_unmanaged_old_core_import_blocks(self) -> None:
        self.root.mkdir(parents=True)
        global_path = self.root / "CLAUDE.md"
        global_path.write_text(
            "@guardpack/versions/2.1.0/00-글로벌-코어.md\n", encoding="utf-8"
        )
        before = global_path.read_bytes()
        result = self.run_install(apply=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("without the managed marker block", result.stdout)
        self.assertEqual(global_path.read_bytes(), before)

    def test_broken_global_symlink_is_not_replaced(self) -> None:
        self.root.mkdir(parents=True)
        global_path = self.root / "CLAUDE.md"
        global_path.symlink_to(self.root / "missing-target.md")
        before = os.readlink(global_path)
        result = self.run_install(apply=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("global memory is a symlink", result.stdout)
        self.assertTrue(global_path.is_symlink())
        self.assertEqual(os.readlink(global_path), before)

    def test_absent_global_created_after_preflight_is_not_overwritten(self) -> None:
        concurrent_text = "# concurrent user content\n"
        real_snapshot = installer.read_source_snapshot

        def create_concurrent_global(pack: Path) -> dict[str, bytes]:
            self.root.mkdir(parents=True, exist_ok=True)
            (self.root / "CLAUDE.md").write_text(concurrent_text, encoding="utf-8")
            return real_snapshot(pack)

        arguments = [
            str(INSTALL), "--pack", str(PACK), "--config-root", str(self.root), "--apply"
        ]
        output = StringIO()
        with mock.patch.object(sys, "argv", arguments), mock.patch.object(
            installer, "read_source_snapshot", side_effect=create_concurrent_global
        ), redirect_stdout(output):
            result = installer.main()
        self.assertEqual(result, 1)
        self.assertIn("anchored installation failed", output.getvalue())
        self.assertEqual((self.root / "CLAUDE.md").read_text(encoding="utf-8"), concurrent_text)

    def test_dangling_global_symlink_created_after_preflight_is_not_replaced(self) -> None:
        global_path = self.root / "CLAUDE.md"
        real_snapshot = installer.read_source_snapshot

        def create_dangling_global(pack: Path) -> dict[str, bytes]:
            self.root.mkdir(parents=True, exist_ok=True)
            global_path.symlink_to(self.root / "missing-global-target.md")
            return real_snapshot(pack)

        arguments = [
            str(INSTALL), "--pack", str(PACK), "--config-root", str(self.root), "--apply"
        ]
        output = StringIO()
        with mock.patch.object(sys, "argv", arguments), mock.patch.object(
            installer, "read_source_snapshot", side_effect=create_dangling_global
        ), redirect_stdout(output):
            result = installer.main()
        self.assertEqual(result, 1)
        self.assertIn("anchored installation failed", output.getvalue())
        self.assertTrue(global_path.is_symlink())

    def test_dangling_version_symlink_created_after_preflight_is_not_replaced(self) -> None:
        target = self.root / "guardpack" / "versions" / "2.3.7"
        real_snapshot = installer.read_source_snapshot

        def create_dangling_target(pack: Path) -> dict[str, bytes]:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(self.root / "missing-version-target")
            return real_snapshot(pack)

        arguments = [
            str(INSTALL), "--pack", str(PACK), "--config-root", str(self.root), "--apply"
        ]
        output = StringIO()
        with mock.patch.object(sys, "argv", arguments), mock.patch.object(
            installer, "read_source_snapshot", side_effect=create_dangling_target
        ), redirect_stdout(output):
            result = installer.main()
        self.assertEqual(result, 1)
        self.assertIn("anchored installation failed", output.getvalue())
        self.assertTrue(target.is_symlink())
        self.assertFalse((self.root / "CLAUDE.md").exists())

    def test_regular_global_replaced_by_hard_link_after_preflight_is_not_replaced(self) -> None:
        self.root.mkdir(parents=True)
        global_path = self.root / "CLAUDE.md"
        original = b"# same bytes\n"
        global_path.write_bytes(original)

        real_snapshot = installer.read_source_snapshot

        def replace_with_hard_link(pack: Path) -> dict[str, bytes]:
            peer = self.root / "peer.md"
            peer.write_bytes(original)
            global_path.unlink()
            os.link(peer, global_path)
            return real_snapshot(pack)

        arguments = [
            str(INSTALL), "--pack", str(PACK), "--config-root", str(self.root), "--apply"
        ]
        output = StringIO()
        with mock.patch.object(sys, "argv", arguments), mock.patch.object(
            installer, "read_source_snapshot", side_effect=replace_with_hard_link
        ), redirect_stdout(output):
            result = installer.main()
        self.assertEqual(result, 1)
        self.assertIn("anchored installation failed", output.getvalue())
        self.assertEqual(global_path.read_bytes(), original)
        self.assertGreater(global_path.stat().st_nlink, 1)

    def test_concurrent_corrupt_target_is_not_activated(self) -> None:
        target = self.root / "guardpack" / "versions" / "2.3.7"
        real_snapshot = installer.read_source_snapshot

        def create_corrupt_target(pack: Path) -> dict[str, bytes]:
            target.mkdir(parents=True)
            (target / "README.md").write_text("corrupt\n", encoding="utf-8")
            return real_snapshot(pack)

        arguments = [
            str(INSTALL), "--pack", str(PACK), "--config-root", str(self.root), "--apply"
        ]
        output = StringIO()
        with mock.patch.object(sys, "argv", arguments), mock.patch.object(
            installer, "read_source_snapshot", side_effect=create_corrupt_target
        ), redirect_stdout(output):
            result = installer.main()
        self.assertEqual(result, 1)
        self.assertIn("version verification failed", output.getvalue())
        self.assertFalse((self.root / "CLAUDE.md").exists())

    def test_post_activation_target_loss_rolls_back_global_marker(self) -> None:
        target = self.root / "guardpack" / "versions" / "2.3.7"
        real_activate = installer.conditional_activate_at
        calls = 0

        def write_then_remove_target(*args: object, **kwargs: object) -> object:
            nonlocal calls
            calls += 1
            result = real_activate(*args, **kwargs)
            if calls == 1:
                (target / "README.md").unlink()
            return result

        arguments = [
            str(INSTALL), "--pack", str(PACK), "--config-root", str(self.root), "--apply"
        ]
        output = StringIO()
        with mock.patch.object(sys, "argv", arguments), mock.patch.object(
            installer, "conditional_activate_at", side_effect=write_then_remove_target
        ), redirect_stdout(output):
            result = installer.main()
        self.assertEqual(result, 1)
        self.assertIn("post-activation version verification failed", output.getvalue())
        self.assertIn("removed new global", output.getvalue())
        self.assertFalse((self.root / "CLAUDE.md").exists())

    def test_edit_in_final_activation_window_is_preserved_and_blocks(self) -> None:
        self.root.mkdir(parents=True)
        global_path = self.root / "CLAUDE.md"
        global_path.write_text("# preflight\n", encoding="utf-8")
        concurrent = "# concurrent final-window edit\n"
        real_backup = installer.secure_backup_at
        calls = 0

        def edit_after_backup(*args: object, **kwargs: object) -> object:
            nonlocal calls
            calls += 1
            result = real_backup(*args, **kwargs)
            if calls == 1:
                global_path.write_text(concurrent, encoding="utf-8")
            return result

        arguments = [
            str(INSTALL), "--pack", str(PACK), "--config-root", str(self.root), "--apply"
        ]
        output = StringIO()
        with mock.patch.object(sys, "argv", arguments), mock.patch.object(
            installer, "secure_backup_at", side_effect=edit_after_backup
        ), redirect_stdout(output):
            result = installer.main()
        self.assertEqual(result, 1)
        self.assertIn("changed before activation", output.getvalue())
        self.assertEqual(global_path.read_text(encoding="utf-8"), concurrent)

    def test_config_root_or_managed_directory_file_blocks_without_traceback(self) -> None:
        self.root.write_text("not a directory\n", encoding="utf-8")
        for apply in (False, True):
            with self.subTest(apply=apply):
                result = self.run_install(apply=apply)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("RESULT: BLOCKED before writes", result.stdout)
                self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_static_managed_symlinks_never_receive_writes(self) -> None:
        for relative in ("guardpack", "guardpack/versions", "guardpack/backups"):
            with self.subTest(relative=relative):
                case_root = self.root.parent / ("case-" + relative.replace("/", "-"))
                outside = self.root.parent / ("outside-" + relative.replace("/", "-"))
                outside.mkdir()
                link = case_root / relative
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(outside, target_is_directory=True)
                command = [
                    sys.executable, "-B", str(INSTALL), "--pack", str(PACK),
                    "--config-root", str(case_root), "--apply",
                ]
                result = subprocess.run(command, text=True, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("RESULT: BLOCKED before writes", result.stdout)
                self.assertEqual(list(outside.iterdir()), [])

    def test_managed_ancestor_swap_cannot_redirect_backup_or_activate(self) -> None:
        self.root.mkdir(parents=True)
        global_path = self.root / "CLAUDE.md"
        original = b"# private preflight\n"
        global_path.write_bytes(original)
        outside = self.root.parent / "outside-race"
        outside.mkdir()
        displaced = self.root / "guardpack-displaced"
        real_backup = installer.secure_backup_at

        def swap_then_backup(*args: object, **kwargs: object) -> object:
            (self.root / "guardpack").rename(displaced)
            (self.root / "guardpack").symlink_to(outside, target_is_directory=True)
            return real_backup(*args, **kwargs)

        arguments = [
            str(INSTALL), "--pack", str(PACK), "--config-root", str(self.root), "--apply"
        ]
        output = StringIO()
        with mock.patch.object(sys, "argv", arguments), mock.patch.object(
            installer, "secure_backup_at", side_effect=swap_then_backup
        ), redirect_stdout(output):
            result = installer.main()
        self.assertEqual(result, 1)
        self.assertIn("managed directory entry changed", output.getvalue())
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(global_path.read_bytes(), original)
        self.assertTrue(list((displaced / "backups").glob("*/CLAUDE.md")))

    def test_failed_publish_with_added_hardlink_never_leaves_active_marker(self) -> None:
        for existed in (False, True):
            with self.subTest(existed=existed):
                case = self.root.parent / ("activation-existing" if existed else "activation-new")
                transaction = case / "transaction"
                transaction.mkdir(parents=True)
                original = b"# original\n"
                if existed:
                    (case / "CLAUDE.md").write_bytes(original)
                config_fd = os.open(case, installer.directory_flags())
                transaction_fd = os.open(transaction, installer.directory_flags())
                try:
                    if existed:
                        expected_bytes, metadata = installer.read_regular_at(config_fd, "CLAUDE.md")
                        expected_metadata = installer.metadata_signature(metadata)
                        previous_mode = metadata.st_mode
                    else:
                        expected_bytes = None
                        expected_metadata = None
                        previous_mode = None
                    real_verify = installer.verify_published_stage_at
                    added = False

                    def add_hardlink(*args: object, **kwargs: object) -> object:
                        nonlocal added
                        if not added:
                            os.link(
                                "CLAUDE.md", "concurrent-peer",
                                src_dir_fd=config_fd, dst_dir_fd=config_fd,
                                follow_symlinks=False,
                            )
                            added = True
                        return real_verify(*args, **kwargs)

                    with mock.patch.object(
                        installer, "verify_published_stage_at", side_effect=add_hardlink
                    ):
                        with self.assertRaises(installer.ConcurrentChangeError):
                            installer.conditional_activate_at(
                                config_fd,
                                transaction_fd,
                                "# planned marker\n",
                                previous_mode,
                                expected_bytes,
                                expected_metadata,
                            )
                finally:
                    os.close(transaction_fd)
                    os.close(config_fd)
                if existed:
                    self.assertEqual((case / "CLAUDE.md").read_bytes(), original)
                else:
                    self.assertFalse((case / "CLAUDE.md").exists())

    def test_empty_or_invalid_utf8_core_blocks_without_traceback(self) -> None:
        for body in (b"", b"\xff\xfe"):
            with self.subTest(body=body):
                candidate = self.root.parent / ("pack-" + body.hex())
                shutil.copytree(PACK, candidate)
                (candidate / "00-글로벌-코어.md").write_bytes(body)
                result = self.run_install(pack=candidate)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("RESULT: BLOCKED before writes", result.stdout)
                self.assertNotIn("Traceback", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
