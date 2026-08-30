#!/usr/bin/env python3
"""Regression tests for the guardpack's structural verifier."""

from __future__ import annotations

import os
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import unicodedata
from pathlib import Path
from unittest import mock


PACK = Path(__file__).resolve().parents[1]
VERIFY = PACK / "verify_guardpack.py"
sys.path.insert(0, str(PACK))
import verify_guardpack as verifier  # noqa: E402
BEGIN = "<!-- VIBECODING_GUARDPACK_BEGIN -->"
END = "<!-- VIBECODING_GUARDPACK_END -->"
IMPORT = "@guardpack/versions/2.3.7/00-글로벌-코어.md"
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


class VerifyGuardpackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="guardpack-verifier-test-")
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def make_global(self, extra: str = "") -> Path:
        installed = self.root / "guardpack" / "versions" / "2.3.7"
        installed.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PACK / "00-글로벌-코어.md", installed / "00-글로벌-코어.md")
        global_path = self.root / "CLAUDE.md"
        global_path.write_text(
            f"{BEGIN}\n{IMPORT}\n{END}\n{extra}", encoding="utf-8"
        )
        return global_path

    def run_verify(
        self,
        global_path: Path | None = None,
        pack: Path = PACK,
        installed: Path | None = None,
        config_root: Path | None = None,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, "-B", str(pack / "verify_guardpack.py"), "--pack", str(pack)]
        if global_path is not None:
            command.extend(["--global-claude", str(global_path)])
        if installed is not None:
            command.extend(["--installed", str(installed)])
        if config_root is not None:
            command.extend(["--config-root", str(config_root)])
        if cwd is not None:
            command.extend(["--cwd", str(cwd)])
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(command, text=True, capture_output=True, env=environment)

    def make_personal_skill(
        self,
        name: str,
        description: str,
        *,
        disable_model_invocation: str | None = None,
    ) -> Path:
        path = self.root / "skills" / name / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        fields = ["---", f"name: {name}", f'description: "{description}"']
        if disable_model_invocation is not None:
            fields.append(f"disable-model-invocation: {disable_model_invocation}")
        fields.extend(["---", "", f"# {name}", ""])
        path.write_text("\n".join(fields), encoding="utf-8")
        return path

    def test_clean_fixture_passes(self) -> None:
        result = self.run_verify(self.make_global())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("RESULT: PASS (structural checks only)", result.stdout)

    def test_v23_distribution_files_are_required(self) -> None:
        self.assertTrue(V23_DISTRIBUTION_FILES.issubset(set(verifier.REQUIRED)))

    def test_closed_manifest_covers_every_shipped_source_file(self) -> None:
        actual = {
            path.relative_to(PACK).as_posix()
            for path in PACK.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and ".pytest_cache" not in path.parts
            and ".git" not in path.parts
            and path.name not in {".DS_Store", ".gitignore", "LICENSE"}
            and path.suffix != ".pyc"
        }
        self.assertEqual(set(verifier.REQUIRED), actual)

    def test_clean_installed_tree_passes_closed_manifest_and_hash_checks(self) -> None:
        installed = self.root / "installed"
        installed.mkdir()
        for relative in verifier.REQUIRED:
            target = installed / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PACK / relative, target)

        result = self.run_verify(installed=installed)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("RESULT: PASS (partial; user global memory/imports were not checked)", result.stdout)

    def test_missing_or_tampered_v23_payload_fails_installed_verification(self) -> None:
        installed = self.root / "installed"
        installed.mkdir()
        for relative in verifier.REQUIRED:
            target = installed / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PACK / relative, target)

        missing = installed / "docs/EVALUATION.md"
        missing_body = missing.read_bytes()
        missing.unlink()
        result = self.run_verify(installed=installed)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("installed file missing: docs/EVALUATION.md", result.stdout)
        missing.write_bytes(missing_body)

        skill_relative = "skills/guardpack-context-intent/SKILL.md"
        (installed / skill_relative).write_text("tampered\n", encoding="utf-8")
        result = self.run_verify(installed=installed)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"installed hash mismatch: {skill_relative}", result.stdout)

    def test_finder_and_bytecode_artifacts_are_not_installed_extra_files(self) -> None:
        # AUD-VER-07: opening the folder in Finder must not block reuse/verification.
        installed = self.root / "installed"
        installed.mkdir()
        for relative in verifier.REQUIRED:
            target = installed / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PACK / relative, target)
        (installed / ".DS_Store").write_bytes(b"\x00")
        cache = installed / "skills" / "__pycache__"
        cache.mkdir()
        (cache / "x.cpython-39.pyc").write_bytes(b"\x00")

        result = self.run_verify(installed=installed)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("installed extra file", result.stdout)

    def test_config_root_alone_derives_global_and_installed_when_core_is_present(self) -> None:
        # AUD-OBS-01: a beginner passing only --config-root must not get PASS for a broken core.
        global_path = self.make_global()
        global_path.write_text("# marker block deleted by hand\n", encoding="utf-8")

        result = self.run_verify(config_root=self.root)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--global-claude derived from --config-root", result.stdout)
        self.assertIn("--installed derived from --config-root", result.stdout)
        self.assertIn("RESULT: FAIL", result.stdout)

    def test_config_root_without_core_reports_partial_pass_loudly(self) -> None:
        self.make_personal_skill("formatter", "JSON 파일의 들여쓰기를 정리합니다.")

        result = self.run_verify(config_root=self.root)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("CORE-NOT-INSTALLED", result.stdout)
        self.assertIn("RESULT: PASS (partial", result.stdout)
        self.assertNotIn("RESULT: PASS (structural checks only)", result.stdout)

    def test_installed_extra_file_fails_closed_manifest_check(self) -> None:
        installed = self.root / "installed"
        installed.mkdir()
        for relative in verifier.REQUIRED:
            target = installed / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PACK / relative, target)
        (installed / "unexpected.txt").write_text("extra\n", encoding="utf-8")

        result = self.run_verify(installed=installed)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("installed extra file: unexpected.txt", result.stdout)

    def test_inline_recursive_conflict_fails(self) -> None:
        global_path = self.make_global("- legacy: @legacy-one.md\n")
        (self.root / "legacy-one.md").write_text(
            "See @legacy-two.md for details.\n", encoding="utf-8"
        )
        (self.root / "legacy-two.md").write_text(
            "실패한 수정을 전부 원복한다 — 원인 불명 변경이 얹힌 코드로는 진단이 오염된다.\n",
            encoding="utf-8",
        )
        result = self.run_verify(global_path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("legacy fingerprint candidate 'blanket rollback'", result.stdout)
        self.assertIn(f"{global_path}:4 -> @legacy-one.md", result.stdout)

    def test_import_beyond_documented_four_hops_fails(self) -> None:
        global_path = self.make_global("See @level-one.md\n")
        names = ["level-one.md", "level-two.md", "level-three.md", "level-four.md", "level-five.md"]
        for index, name in enumerate(names):
            body = "terminal\n" if index == len(names) - 1 else f"See @{names[index + 1]}\n"
            (self.root / name).write_text(body, encoding="utf-8")
        result = self.run_verify(global_path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("import exceeds 4-hop limit", result.stdout)

    def test_global_body_conflict_fails(self) -> None:
        result = self.run_verify(
            self.make_global(
                "실패한 수정을 전부 원복한다 — 원인 불명 변경이 얹힌 코드로는 진단이 오염된다.\n"
            )
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("legacy fingerprint candidate 'blanket rollback'", result.stdout)

    def test_zero_width_and_decomposed_hangul_cannot_bypass_fingerprint(self) -> None:
        legacy = self.root / "legacy.md"
        canonical = (
            "실패한 수정을 전부 원복한다 — 원인 불명 변경이 얹힌 코드로는 진단이 오염된다.\n"
        )
        for body in (
            canonical.replace("실패한", "실\u200b패한"),
            unicodedata.normalize("NFD", canonical),
        ):
            with self.subTest(body=body):
                legacy.write_text(body, encoding="utf-8")
                result = self.run_verify(self.make_global("@legacy.md\n"))
                self.assertNotEqual(result.returncode, 0)
                if "\u200b" in body:
                    self.assertIn("hidden control/zero-width", result.stdout)
                else:
                    self.assertIn("legacy fingerprint candidate 'blanket rollback'", result.stdout)

    def test_stable_hash_detects_path_replacement_during_read(self) -> None:
        target = self.root / "target.md"
        peer = self.root / "peer.md"
        target.write_bytes(b"same bytes\n")
        peer.write_bytes(b"same bytes\n")
        real_read = verifier.os.read
        replaced = False

        def replace_after_read(descriptor: int, size: int) -> bytes:
            nonlocal replaced
            chunk = real_read(descriptor, size)
            if chunk and not replaced:
                replaced = True
                target.unlink()
                target.symlink_to(peer)
            return chunk

        with mock.patch.object(verifier.os, "read", side_effect=replace_after_read):
            with self.assertRaises(OSError):
                verifier.sha256(target)

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
                result = self.run_verify(self.make_global())
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("legacy fingerprint candidate 'blanket rollback'", result.stdout)

    def test_top_level_paths_frontmatter_remains_task_scoped(self) -> None:
        rules = self.root / "rules"
        rules.mkdir(parents=True)
        (rules / "scoped.md").write_text(
            "---\npaths: [\"src/**\"]\n---\n"
            "실패한 수정을 전부 원복한다 — 원인 불명 변경이 얹힌 코드로는 진단이 오염된다.\n",
            encoding="utf-8",
        )
        result = self.run_verify(self.make_global())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("path-scoped rule needs task-specific audit", result.stdout)

    def test_cli_symlink_loop_paths_fail_without_traceback(self) -> None:
        loop = self.root / "loop"
        loop.symlink_to(loop)
        for option in ("--pack", "--global-claude", "--rules-dir", "--cwd", "--installed"):
            with self.subTest(option=option):
                command = [sys.executable, "-B", str(VERIFY), option, str(loop)]
                if option != "--pack":
                    command.extend(["--pack", str(PACK)])
                result = subprocess.run(command, text=True, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("RESULT: FAIL", result.stdout)
                self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_global_symlink_is_not_certified(self) -> None:
        real = self.make_global()
        link = self.root / "linked-global.md"
        link.symlink_to(real)
        result = self.run_verify(link)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("global memory is a symlink", result.stdout)

    def test_code_examples_and_safe_negation_do_not_false_positive(self) -> None:
        extra = (
            "`@missing-inline.md`\n"
            "```md\n@missing-fenced.md\n실패한 수정을 전부 원복한다.\n```\n"
            "원인 가설 3개를 강제하지 않는다.\n"
        )
        result = self.run_verify(self.make_global(extra))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_mismatched_or_unclosed_backticks_do_not_hide_imports(self) -> None:
        legacy = self.root / "legacy.md"
        legacy.write_text(
            "실패한 수정을 전부 원복한다 — 원인 불명 변경이 얹힌 코드로는 진단이 오염된다.\n",
            encoding="utf-8",
        )
        for malformed in ("` @legacy.md ``", "`` @legacy.md `", "` @legacy.md"):
            with self.subTest(malformed=malformed):
                result = self.run_verify(self.make_global(malformed + "\n"))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("legacy fingerprint candidate 'blanket rollback'", result.stdout)

    def test_escaped_backticks_do_not_hide_imports(self) -> None:
        (self.root / "legacy.md").write_text(
            "실패한 수정을 전부 원복한다 — 원인 불명 변경이 얹힌 코드로는 진단이 오염된다.\n",
            encoding="utf-8",
        )
        result = self.run_verify(self.make_global(r"\` @legacy.md \`" + "\n"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("legacy fingerprint candidate 'blanket rollback'", result.stdout)

    def test_escaped_or_malformed_html_comment_does_not_hide_imports(self) -> None:
        (self.root / "legacy.md").write_text(
            "실패한 수정을 전부 원복한다 — 원인 불명 변경이 얹힌 코드로는 진단이 오염된다.\n",
            encoding="utf-8",
        )
        for body in (
            r"\<!-- @legacy.md -->",
            "<!-- outer <!-- @legacy.md -->",
            "<!--> @legacy.md -->",
            "<!-- -- @legacy.md -->",
            "<!-- @legacy.md --->",
            "`<!--` @legacy.md `-->`",
        ):
            with self.subTest(body=body):
                result = self.run_verify(self.make_global(body + "\n"))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("legacy fingerprint candidate 'blanket rollback'", result.stdout)

    def test_invalid_backtick_fence_opener_does_not_hide_import(self) -> None:
        (self.root / "legacy.md").write_text(
            "실패한 수정을 전부 원복한다 — 원인 불명 변경이 얹힌 코드로는 진단이 오염된다.\n",
            encoding="utf-8",
        )
        result = self.run_verify(
            self.make_global("```foo`bar\n@legacy.md\n```\n")
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("legacy fingerprint candidate 'blanket rollback'", result.stdout)

    def test_reversed_markers_fail(self) -> None:
        global_path = self.make_global()
        global_path.write_text(f"{END}\n{IMPORT}\n{BEGIN}\n", encoding="utf-8")
        result = self.run_verify(global_path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("markers are reversed", result.stdout)

    def test_import_outside_managed_block_fails(self) -> None:
        global_path = self.make_global()
        global_path.write_text(f"{BEGIN}\n{END}\n{IMPORT}\n", encoding="utf-8")
        result = self.run_verify(global_path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("managed block must contain only", result.stdout)

    def test_other_guardpack_core_outside_managed_block_fails(self) -> None:
        global_path = self.make_global("@guardpack/versions/2.1.0/00-글로벌-코어.md\n")
        old_core = self.root / "guardpack" / "versions" / "2.1.0" / "00-글로벌-코어.md"
        old_core.parent.mkdir(parents=True)
        old_core.write_text("harmless old core\n", encoding="utf-8")
        result = self.run_verify(global_path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("guardpack core import outside or beyond", result.stdout)

    def test_indented_import_is_conservatively_treated_as_active(self) -> None:
        result = self.run_verify(self.make_global("    @missing-indented.md\n"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("referenced import is missing", result.stdout)

    def test_four_space_indented_fence_does_not_hide_import(self) -> None:
        extra = "    ```md\n    @missing-inside-indented-fence.md\n    ```\n"
        result = self.run_verify(self.make_global(extra))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("referenced import is missing", result.stdout)

    def test_comment_cannot_replace_test_row(self) -> None:
        candidate = self.root / "pack"
        shutil.copytree(PACK, candidate)
        test_path = candidate / "09-행동-회귀-테스트.md"
        lines = test_path.read_text(encoding="utf-8").splitlines()
        changed = ["<!-- T29 -->" if line.startswith("| T29 |") else line for line in lines]
        test_path.write_text("\n".join(changed) + "\n", encoding="utf-8")
        result = self.run_verify(pack=candidate)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("behavior test rows missing: T29", result.stdout)

    def test_hidden_full_test_row_cannot_replace_oracle(self) -> None:
        candidate = self.root / "pack"
        shutil.copytree(PACK, candidate)
        test_path = candidate / "09-행동-회귀-테스트.md"
        lines = test_path.read_text(encoding="utf-8").splitlines()
        changed = [
            "<!-- | T29 | hidden | fake pass | fake fail | -->"
            if line.startswith("| T29 |")
            else line
            for line in lines
        ]
        test_path.write_text("\n".join(changed) + "\n", encoding="utf-8")
        result = self.run_verify(pack=candidate)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("behavior test rows missing: T29", result.stdout)

    def test_core_signal_hidden_in_comment_cannot_satisfy_linter(self) -> None:
        candidate = self.root / "pack"
        shutil.copytree(PACK, candidate)
        core_path = candidate / "00-글로벌-코어.md"
        core = core_path.read_text(encoding="utf-8")
        core_path.write_text(
            core.replace("합의 수는 증거가 아니다.", "<!-- 합의 수는 증거가 아니다. -->"),
            encoding="utf-8",
        )
        result = self.run_verify(pack=candidate)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("core missing regression signal: 합의 수는 증거가 아니다", result.stdout)

    def test_duplicate_test_row_fails(self) -> None:
        candidate = self.root / "pack"
        shutil.copytree(PACK, candidate)
        test_path = candidate / "09-행동-회귀-테스트.md"
        test_path.write_text(
            test_path.read_text(encoding="utf-8")
            + "| T13 | duplicate | contradictory | oracle |\n",
            encoding="utf-8",
        )
        result = self.run_verify(pack=candidate)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("behavior test rows duplicated: T13", result.stdout)

    def test_missing_machine_readable_case_fails(self) -> None:
        candidate = self.root / "pack"
        shutil.copytree(PACK, candidate)
        cases_path = candidate / "behavior-fixtures" / "cases.jsonl"
        lines = cases_path.read_text(encoding="utf-8").splitlines()
        cases_path.write_text(
            "\n".join(line for line in lines if not line.startswith('{"id":"T29"')) + "\n",
            encoding="utf-8",
        )
        result = self.run_verify(pack=candidate)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("behavior fixture cases missing: T29", result.stdout)

    def test_weakened_run_record_schema_fails(self) -> None:
        candidate = self.root / "pack"
        shutil.copytree(PACK, candidate)
        schema_path = candidate / "behavior-fixtures" / "run-record.schema.json"
        schema = schema_path.read_text(encoding="utf-8")
        schema = schema.replace('"evidence": {"minItems": 1}', '"evidence": {"minItems": 0}', 1)
        schema_path.write_text(schema, encoding="utf-8")
        result = self.run_verify(pack=candidate)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("lacks the pass/fail evidence and isolation gate", result.stdout)

    def test_weakened_evaluation_plan_schema_fails(self) -> None:
        candidate = self.root / "pack-evaluation-plan"
        shutil.copytree(PACK, candidate)
        schema_path = candidate / "behavior-fixtures" / "evaluation-plan.schema.json"
        schema = schema_path.read_text(encoding="utf-8")
        schema = schema.replace('"repeats": {"const": 3}', '"repeats": {"minimum": 1}', 1)
        schema_path.write_text(schema, encoding="utf-8")
        result = self.run_verify(pack=candidate)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not lock the official 7x2x3 pilot", result.stdout)

    def test_stale_pilot_case_counts_fail(self) -> None:
        mutations = (
            (
                "09-행동-회귀-테스트.md",
                "7 case×2조건×3회",
                "6 case×2조건×3회",
            ),
            (
                "docs/EVALUATION.md",
                "선택한 7개 실행 fixture",
                "선택한 6개 실행 fixture",
            ),
            (
                "docs/EVALUATION.md",
                "7개 case pilot 도구",
                "6개 case pilot 도구",
            ),
        )
        for index, (relative, current, stale) in enumerate(mutations):
            with self.subTest(relative=relative, claim=current):
                candidate = self.root / f"pack-stale-pilot-counts-{index}"
                shutil.copytree(PACK, candidate)
                path = candidate / relative
                path.write_text(
                    path.read_text(encoding="utf-8").replace(current, stale, 1),
                    encoding="utf-8",
                )
                result = self.run_verify(pack=candidate)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    f"{relative} pilot case count is 6, expected 7",
                    result.stdout,
                )

    def test_malformed_schema_containers_fail_without_traceback(self) -> None:
        candidate = self.root / "pack"
        shutil.copytree(PACK, candidate)
        schema_path = candidate / "behavior-fixtures" / "run-record.schema.json"
        schema_path.write_text(
            '{"type":"object","required":[{}],"properties":[],"allOf":{}}\n',
            encoding="utf-8",
        )
        result = self.run_verify(pack=candidate)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("required must be an array of strings", result.stdout)
        self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_malformed_nested_schema_container_fails_without_traceback(self) -> None:
        candidate = self.root / "pack"
        shutil.copytree(PACK, candidate)
        schema_path = candidate / "behavior-fixtures" / "run-record.schema.json"
        schema = __import__("json").loads(schema_path.read_text(encoding="utf-8"))
        schema["allOf"] = [{"if": []}]
        schema_path.write_text(__import__("json").dumps(schema) + "\n", encoding="utf-8")
        result = self.run_verify(pack=candidate)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("lacks the pass/fail evidence and isolation gate", result.stdout)
        self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_invalid_utf8_cases_and_schema_fail_without_traceback(self) -> None:
        for relative in (
            "behavior-fixtures/cases.jsonl",
            "behavior-fixtures/evaluation-plan.schema.json",
            "behavior-fixtures/run-record.schema.json",
        ):
            with self.subTest(relative=relative):
                candidate = self.root / ("pack-" + relative.replace("/", "-"))
                shutil.copytree(PACK, candidate)
                (candidate / relative).write_bytes(b"\xff\xfe")
                result = self.run_verify(pack=candidate)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("not valid UTF-8", result.stdout)
                self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_duplicate_keys_or_nonstandard_numbers_fail_json_contracts(self) -> None:
        candidate = self.root / "pack-duplicate-json"
        shutil.copytree(PACK, candidate)
        cases = candidate / "behavior-fixtures/cases.jsonl"
        text = cases.read_text(encoding="utf-8")
        cases.write_text(text.replace('{"id":"T01"', '{"id":"T01","id":"T01"', 1), encoding="utf-8")
        result = self.run_verify(pack=candidate)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate JSON object key", result.stdout)

        candidate_nan = self.root / "pack-nan-json"
        shutil.copytree(PACK, candidate_nan)
        schema = candidate_nan / "behavior-fixtures/run-record.schema.json"
        schema.write_text('{"type":"object","x":NaN}\n', encoding="utf-8")
        result = self.run_verify(pack=candidate_nan)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("non-standard JSON numeric constant", result.stdout)

    def test_self_symlink_import_fails_without_traceback(self) -> None:
        global_path = self.make_global("@loop.md\n")
        (self.root / "loop.md").symlink_to(self.root / "loop.md")
        result = self.run_verify(global_path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("referenced import cannot be resolved", result.stdout)
        self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_self_symlink_guardpack_directory_fails_without_traceback(self) -> None:
        global_path = self.make_global()
        shutil.rmtree(self.root / "guardpack")
        (self.root / "guardpack").symlink_to(self.root / "guardpack")
        result = self.run_verify(global_path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("managed v2.3.7 core import cannot be resolved", result.stdout)
        self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_behavior_case_requires_typed_safe_fixture_contract(self) -> None:
        candidate = self.root / "pack"
        shutil.copytree(PACK, candidate)
        cases_path = candidate / "behavior-fixtures" / "cases.jsonl"
        text = cases_path.read_text(encoding="utf-8")
        text = text.replace(
            '"id":"T13","setup":"실제 서비스와 분리된 mock 운영 DB 이름을 모호하게 제시한다."',
            '"id":"T13","setup":13',
        ).replace(
            '"safe_fixture_only":true}', '"safe_fixture_only":"false"}', 1
        )
        cases_path.write_text(text, encoding="utf-8")
        result = self.run_verify(pack=candidate)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("has no setup string", result.stdout)
        self.assertIn("must require a safe isolated fixture", result.stdout)

    def test_missing_global_is_reported_without_traceback(self) -> None:
        result = self.run_verify(self.root / "missing" / "CLAUDE.md")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("instruction file missing", result.stdout)
        self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_installed_symlink_is_not_certified_by_matching_hash(self) -> None:
        installed = self.root / "installed"
        shutil.copytree(PACK, installed)
        target = installed / "README.md"
        target.unlink()
        target.symlink_to(PACK / "README.md")
        result = self.run_verify(installed=installed)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("installed path is a symlink: README.md", result.stdout)

    def test_installed_root_symlink_is_not_certified(self) -> None:
        link = self.root / "installed-link"
        link.symlink_to(PACK)
        result = self.run_verify(installed=link)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("installed root is a symlink", result.stdout)

    def test_installed_directory_ancestor_symlink_is_not_certified(self) -> None:
        installed = self.root / "installed"
        shutil.copytree(PACK, installed)
        external = self.root / "external-docs"
        shutil.copytree(PACK / "docs", external)
        shutil.rmtree(installed / "docs")
        (installed / "docs").symlink_to(external)
        result = self.run_verify(installed=installed)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("installed ancestor is a symlink", result.stdout)

    def test_installed_hard_link_is_not_certified_by_matching_hash(self) -> None:
        installed = self.root / "installed"
        shutil.copytree(PACK, installed)
        target = installed / "README.md"
        peer = self.root / "README-peer.md"
        peer.write_bytes((PACK / "README.md").read_bytes())
        target.unlink()
        os.link(peer, target)
        result = self.run_verify(installed=installed)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("installed path is a hard link: README.md", result.stdout)

    def test_known_personal_audit_is_one_warn_only_candidate(self) -> None:
        self.make_personal_skill(
            "audit",
            "작은 코드도 견고성 감사와 여러 모델의 적대 검증으로 점검합니다.",
        )

        result = self.run_verify(config_root=self.root)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count("ROUTING-POLICY: audit"), 1)
        self.assertIn("T19", result.stdout)
        self.assertNotIn("FAIL: ROUTING", result.stdout)
        self.assertNotIn("BLOCK:", result.stdout)
        self.assertIn("RESULT: PASS (partial; user global memory/imports were not checked)", result.stdout)

    def test_unrelated_and_manual_skills_do_not_warn(self) -> None:
        self.make_personal_skill("formatter", "JSON 파일의 들여쓰기를 정리합니다.")
        self.make_personal_skill(
            "audit",
            "프로젝트 견고성을 감사합니다.",
            disable_model_invocation="true",
        )

        result = self.run_verify(config_root=self.root)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("ROUTING-POLICY:", result.stdout)
        self.assertNotIn("ROUTING-OVERLAP:", result.stdout)

    def test_user_invocable_only_override_excludes_personal_skill(self) -> None:
        self.make_personal_skill("audit", "프로젝트 견고성 감사")
        (self.root / "settings.json").write_text(
            '{"skillOverrides":{"audit":"user-invocable-only"}}\n',
            encoding="utf-8",
        )

        result = self.run_verify(config_root=self.root)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("ROUTING-POLICY: audit", result.stdout)

    def test_personal_skill_uses_directory_name_not_frontmatter_display_name(self) -> None:
        path = self.make_personal_skill("audit", "프로젝트 견고성 감사")
        path.write_text(
            "---\n"
            "name: display-only-label\n"
            "description: 프로젝트 견고성 감사\n"
            "---\n",
            encoding="utf-8",
        )

        result = self.run_verify(config_root=self.root)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ROUTING-POLICY: audit", result.stdout)
        self.assertNotIn("ROUTING-POLICY: display-only-label", result.stdout)

    def test_name_only_override_does_not_scan_hidden_description(self) -> None:
        self.make_personal_skill(
            "source-check",
            "출처 기반 조사와 비교 검토를 자동으로 수행합니다.",
        )
        (self.root / "settings.json").write_text(
            '{"skillOverrides":{"source-check":"name-only"}}\n',
            encoding="utf-8",
        )

        result = self.run_verify(config_root=self.root)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("ROUTING-OVERLAP: source-check", result.stdout)

    def test_listing_text_after_runtime_cap_does_not_create_overlap(self) -> None:
        path = self.make_personal_skill("long-description", "placeholder")
        path.write_text(
            "---\n"
            "description: " + ("x" * 1536) + " 출처 기반 조사 비교 검토\n"
            "---\n",
            encoding="utf-8",
        )

        result = self.run_verify(config_root=self.root)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("ROUTING-OVERLAP: long-description", result.stdout)

    def test_flat_command_without_disable_is_auto_invocation_candidate(self) -> None:
        commands = self.root / "commands"
        commands.mkdir(parents=True)
        (commands / "feature-dev.md").write_text(
            "---\ndescription: Guided feature development\n---\n\nAsk every question first.\n",
            encoding="utf-8",
        )

        result = self.run_verify(config_root=self.root)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ROUTING-POLICY: feature-dev", result.stdout)
        self.assertIn("T02", result.stdout)
        self.assertIn("T19", result.stdout)

    def test_when_to_use_participates_in_overlap_warning(self) -> None:
        path = self.make_personal_skill("source-check", "자료를 정리합니다.")
        path.write_text(
            "---\n"
            "name: source-check\n"
            "description: 자료를 정리합니다.\n"
            "when_to_use: 출처 기반 조사와 비교 검토가 필요할 때\n"
            "---\n\n# source check\n",
            encoding="utf-8",
        )

        result = self.run_verify(config_root=self.root)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ROUTING-OVERLAP: source-check", result.stdout)
        self.assertIn("guardpack-evidence-review", result.stdout)

    def test_malformed_and_symlink_skills_are_incomplete_warns_not_failures(self) -> None:
        malformed = self.root / "skills" / "broken" / "SKILL.md"
        malformed.parent.mkdir(parents=True)
        malformed.write_text("---\ndescription: [broken\n---\n", encoding="utf-8")
        link = self.root / "skills" / "linked" / "SKILL.md"
        link.parent.mkdir(parents=True)
        link.symlink_to(malformed)

        result = self.run_verify(config_root=self.root)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ROUTING-SCAN-INCOMPLETE:", result.stdout)
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        self.assertIn("RESULT: PASS (partial; user global memory/imports were not checked)", result.stdout)

    def test_enabled_installed_plugin_custom_command_path_is_scanned(self) -> None:
        plugin = self.root / "plugins" / "cache" / "official" / "feature-dev" / "1.0.0"
        command = plugin / "workflow" / "feature.md"
        command.parent.mkdir(parents=True)
        command.write_text(
            "---\ndescription: Guided feature development\n---\n",
            encoding="utf-8",
        )
        manifest = plugin / ".claude-plugin" / "plugin.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            '{"name":"feature-dev","commands":["./workflow/feature.md"]}\n',
            encoding="utf-8",
        )
        installed = self.root / "plugins" / "installed_plugins.json"
        installed.write_text(
            '{"version":2,"plugins":{"feature-dev@official":['
            f'{{"scope":"user","installPath":"{plugin}","version":"1.0.0"}}]}}}}\n',
            encoding="utf-8",
        )
        (self.root / "settings.json").write_text(
            '{"enabledPlugins":{"feature-dev@official":true}}\n',
            encoding="utf-8",
        )

        result = self.run_verify(config_root=self.root)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ROUTING-POLICY: feature-dev", result.stdout)

    def test_plugin_custom_commands_directory_scans_nested_skill(self) -> None:
        plugin = self.root / "plugins" / "cache" / "official" / "workflow" / "1.0.0"
        skill = plugin / "cmds" / "feature" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(
            "---\nname: feature-dev\ndescription: Guided feature development\n---\n",
            encoding="utf-8",
        )
        manifest = plugin / ".claude-plugin" / "plugin.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            '{"name":"workflow","commands":"./cmds"}\n',
            encoding="utf-8",
        )
        installed = self.root / "plugins" / "installed_plugins.json"
        installed.write_text(
            '{"version":2,"plugins":{"workflow@official":['
            f'{{"scope":"user","installPath":"{plugin}","version":"1.0.0"}}]}}}}\n',
            encoding="utf-8",
        )

        result = self.run_verify(config_root=self.root)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ROUTING-POLICY: feature-dev", result.stdout)

    def test_guardpack_plugin_excludes_itself_from_routing_scan(self) -> None:
        plugin = self.root / "plugins" / "cache" / "local" / "guardpack" / "2.3.7"
        for relative in verifier.SELF_PLUGIN_FILES:
            target = plugin / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PACK / relative, target)
        installed = self.root / "plugins" / "installed_plugins.json"
        installed.write_text(
            '{"version":2,"plugins":{"vibecoding-guardpack@test":['
            f'{{"scope":"user","installPath":"{plugin}","version":"2.3.7"}}]}}}}\n',
            encoding="utf-8",
        )

        result = self.run_verify(config_root=self.root)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("ROUTING-OVERLAP: guardpack-", result.stdout)
        self.assertNotIn("GUARDPACK-PLUGIN-CONTENT-MISMATCH:", result.stdout)
        self.assertNotIn("ROUTING-SCAN-INCOMPLETE:", result.stdout)

    def test_guardpack_self_exclusion_rejects_extra_routing_surfaces(self) -> None:
        for extra_relative, body, expected_policy in (
            (
                "commands/feature-dev.md",
                "---\ndescription: Guided feature development\n---\n",
                "feature-dev",
            ),
            (
                "commands/feature/SKILL.md",
                "---\nname: feature-dev\ndescription: Guided feature development\n---\n",
                "feature-dev",
            ),
            (
                "skills/audit/SKILL.md",
                "---\nname: audit\ndescription: 프로젝트 견고성 감사\n---\n",
                "audit",
            ),
        ):
            with self.subTest(extra_relative=extra_relative):
                config = self.root / extra_relative.replace("/", "-")
                plugin = config / "plugins" / "cache" / "local" / "guardpack" / "2.3.7"
                for relative in verifier.SELF_PLUGIN_FILES:
                    target = plugin / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(PACK / relative, target)
                extra = plugin / extra_relative
                extra.parent.mkdir(parents=True, exist_ok=True)
                extra.write_text(body, encoding="utf-8")
                installed = config / "plugins" / "installed_plugins.json"
                installed.write_text(
                    '{"version":2,"plugins":{"vibecoding-guardpack@test":['
                    f'{{"scope":"user","installPath":"{plugin}","version":"2.3.7"}}]}}}}\n',
                    encoding="utf-8",
                )

                result = self.run_verify(config_root=config)

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("GUARDPACK-PLUGIN-CONTENT-MISMATCH:", result.stdout)
                self.assertIn(f"ROUTING-POLICY: {expected_policy}", result.stdout)

    def test_same_version_tampered_guardpack_is_not_self_excluded(self) -> None:
        plugin = self.root / "plugins" / "cache" / "local" / "guardpack" / "2.3.7"
        for relative in verifier.SELF_PLUGIN_FILES:
            target = plugin / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PACK / relative, target)
        target = plugin / "skills" / "guardpack-completion-check" / "SKILL.md"
        target.write_text(target.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
        installed = self.root / "plugins" / "installed_plugins.json"
        installed.write_text(
            '{"version":2,"plugins":{"vibecoding-guardpack@test":['
            f'{{"scope":"user","installPath":"{plugin}","version":"2.3.7"}}]}}}}\n',
            encoding="utf-8",
        )

        result = self.run_verify(config_root=self.root)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("GUARDPACK-PLUGIN-CONTENT-MISMATCH:", result.stdout)

    def test_old_guardpack_plugin_version_gets_dedicated_warning(self) -> None:
        plugin = self.root / "plugins" / "cache" / "local" / "guardpack" / "2.3.0"
        manifest = plugin / ".claude-plugin" / "plugin.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            '{"name":"vibecoding-guardpack","version":"2.3.0"}\n',
            encoding="utf-8",
        )
        installed = self.root / "plugins" / "installed_plugins.json"
        installed.write_text(
            '{"version":2,"plugins":{"vibecoding-guardpack@test":['
            f'{{"scope":"user","installPath":"{plugin}","version":"2.3.0"}}]}}}}\n',
            encoding="utf-8",
        )

        result = self.run_verify(config_root=self.root)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("GUARDPACK-PLUGIN-VERSION-MISMATCH:", result.stdout)
        self.assertIn("2.3.0", result.stdout)
        self.assertNotIn("ROUTING-OVERLAP: guardpack-", result.stdout)

    def test_old_or_manifestless_guardpack_still_scans_extra_commands(self) -> None:
        for manifest_body in (
            '{"name":"vibecoding-guardpack","version":"2.3.0"}\n',
            None,
        ):
            with self.subTest(manifest_body=manifest_body):
                config = self.root / ("old" if manifest_body else "manifestless")
                plugin = config / "plugins" / "cache" / "local" / "guardpack"
                command = plugin / "commands" / "feature-dev.md"
                command.parent.mkdir(parents=True)
                command.write_text(
                    "---\ndescription: Guided feature development\n---\n",
                    encoding="utf-8",
                )
                if manifest_body is not None:
                    manifest = plugin / ".claude-plugin" / "plugin.json"
                    manifest.parent.mkdir(parents=True)
                    manifest.write_text(manifest_body, encoding="utf-8")
                installed = config / "plugins" / "installed_plugins.json"
                installed.write_text(
                    '{"version":2,"plugins":{"vibecoding-guardpack@test":['
                    f'{{"scope":"user","installPath":"{plugin}","version":"2.3.0"}}]}}}}\n',
                    encoding="utf-8",
                )

                result = self.run_verify(config_root=config)

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("GUARDPACK-PLUGIN-VERSION-MISMATCH:", result.stdout)
                self.assertIn("ROUTING-POLICY: feature-dev", result.stdout)

    def test_only_confirmed_user_scope_plugin_records_are_scanned(self) -> None:
        for scope in ("project", "local", "managed", None):
            with self.subTest(scope=scope):
                config = self.root / (scope or "missing")
                plugin = config / "plugins" / "cache" / "official" / "feature-dev"
                command = plugin / "commands" / "feature-dev.md"
                command.parent.mkdir(parents=True)
                command.write_text(
                    "---\ndescription: Guided feature development\n---\n",
                    encoding="utf-8",
                )
                record = {"installPath": str(plugin), "version": "1.0.0"}
                if scope is not None:
                    record["scope"] = scope
                installed = config / "plugins" / "installed_plugins.json"
                installed.write_text(
                    json.dumps(
                        {"version": 2, "plugins": {"feature-dev@official": [record]}}
                    ),
                    encoding="utf-8",
                )

                result = self.run_verify(config_root=config)

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn("ROUTING-POLICY: feature-dev", result.stdout)
                self.assertIn("ROUTING-SCAN-INCOMPLETE:", result.stdout)

        user_config = self.root / "user"
        user_plugin = user_config / "plugins" / "cache" / "official" / "feature-dev"
        user_command = user_plugin / "commands" / "feature-dev.md"
        user_command.parent.mkdir(parents=True)
        user_command.write_text(
            "---\ndescription: Guided feature development\n---\n",
            encoding="utf-8",
        )
        user_inventory = user_config / "plugins" / "installed_plugins.json"
        user_inventory.write_text(
            json.dumps(
                {
                    "version": 2,
                    "plugins": {
                        "feature-dev@official": [
                            {
                                "scope": "user",
                                "installPath": str(user_plugin),
                                "version": "1.0.0",
                            }
                        ]
                    },
                }
            ),
            encoding="utf-8",
        )
        result = self.run_verify(config_root=user_config)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ROUTING-POLICY: feature-dev", result.stdout)

    def test_skill_override_does_not_hide_installed_plugin_skill(self) -> None:
        plugin = self.root / "plugins" / "cache" / "official" / "audit-pack" / "1.0.0"
        skill = plugin / "skills" / "audit" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(
            "---\nname: audit\ndescription: 프로젝트 견고성 감사\n---\n",
            encoding="utf-8",
        )
        manifest = plugin / ".claude-plugin" / "plugin.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text('{"name":"audit-pack"}\n', encoding="utf-8")
        installed = self.root / "plugins" / "installed_plugins.json"
        installed.write_text(
            '{"version":2,"plugins":{"audit-pack@official":['
            f'{{"scope":"user","installPath":"{plugin}","version":"1.0.0"}}]}}}}\n',
            encoding="utf-8",
        )
        (self.root / "settings.json").write_text(
            '{"enabledPlugins":{"audit-pack@official":true},'
            '"skillOverrides":{"audit":"off"}}\n',
            encoding="utf-8",
        )

        result = self.run_verify(config_root=self.root)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ROUTING-POLICY: audit (plugin skill)", result.stdout)

    def test_cwd_does_not_rescan_personal_skills_as_project_skills(self) -> None:
        home = self.root / "home"
        config = home / ".claude"
        project = home / "work" / "project"
        skill = config / "skills" / "audit" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        project.mkdir(parents=True)
        skill.write_text(
            "---\nname: audit\ndescription: 프로젝트 견고성 감사\n---\n",
            encoding="utf-8",
        )

        result = self.run_verify(config_root=config, cwd=project)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count("ROUTING-POLICY: audit"), 1)
        self.assertNotIn("audit (project skill)", result.stdout)

    def test_personal_skill_shadows_same_name_legacy_command(self) -> None:
        self.make_personal_skill("audit", "프로젝트 견고성 감사")
        command = self.root / "commands" / "audit.md"
        command.parent.mkdir()
        command.write_text(
            "---\ndescription: 작은 점검도 다중 감사\n---\n",
            encoding="utf-8",
        )

        result = self.run_verify(config_root=self.root)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count("ROUTING-POLICY: audit"), 1)
        self.assertIn("audit (personal skill)", result.stdout)
        self.assertNotIn("audit (personal command)", result.stdout)

    def test_manifestless_plugin_default_command_is_scanned(self) -> None:
        plugin = self.root / "plugins" / "cache" / "official" / "feature-dev" / "1.0.0"
        command = plugin / "commands" / "feature-dev.md"
        command.parent.mkdir(parents=True)
        command.write_text(
            "---\ndescription: Guided feature development\n---\n",
            encoding="utf-8",
        )
        installed = self.root / "plugins" / "installed_plugins.json"
        installed.write_text(
            '{"version":2,"plugins":{"feature-dev@official":['
            f'{{"scope":"user","installPath":"{plugin}","version":"1.0.0"}}]}}}}\n',
            encoding="utf-8",
        )

        result = self.run_verify(config_root=self.root)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ROUTING-POLICY: feature-dev", result.stdout)
        self.assertNotIn("manifest is missing", result.stdout)

    def test_manifestless_plugin_default_commands_scans_nested_skill(self) -> None:
        plugin = self.root / "plugins" / "cache" / "official" / "workflow" / "1.0.0"
        skill = plugin / "commands" / "feature" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(
            "---\nname: feature-dev\ndescription: Guided feature development\n---\n",
            encoding="utf-8",
        )
        installed = self.root / "plugins" / "installed_plugins.json"
        installed.write_text(
            '{"version":2,"plugins":{"workflow@official":['
            f'{{"scope":"user","installPath":"{plugin}","version":"1.0.0"}}]}}}}\n',
            encoding="utf-8",
        )

        result = self.run_verify(config_root=self.root)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ROUTING-POLICY: feature-dev", result.stdout)

    def test_install_path_dotdot_escape_is_not_read(self) -> None:
        config = self.root / "config"
        outside = self.root / "outside-feature-dev"
        command = outside / "commands" / "feature-dev.md"
        command.parent.mkdir(parents=True)
        command.write_text(
            "---\ndescription: Guided feature development\n---\n",
            encoding="utf-8",
        )
        manifest = outside / ".claude-plugin" / "plugin.json"
        manifest.parent.mkdir()
        manifest.write_text('{"name":"feature-dev"}\n', encoding="utf-8")
        raw_path = config / "plugins" / ".." / ".." / outside.name
        inventory = config / "plugins" / "installed_plugins.json"
        inventory.parent.mkdir(parents=True)
        inventory.write_text(
            json.dumps(
                {
                    "version": 2,
                    "plugins": {
                        "feature-dev@official": [
                            {"scope": "user", "installPath": str(raw_path), "version": "1.0.0"}
                        ]
                    },
                }
            ),
            encoding="utf-8",
        )

        result = self.run_verify(config_root=config)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ROUTING-SCAN-INCOMPLETE:", result.stdout)
        self.assertNotIn("ROUTING-POLICY: feature-dev", result.stdout)

    def test_plugin_custom_path_intermediate_symlink_is_not_followed(self) -> None:
        config = self.root / "config"
        outside = self.root / "outside-command"
        outside.mkdir()
        (outside / "feature-dev.md").write_text(
            "---\ndescription: Guided feature development\n---\n",
            encoding="utf-8",
        )
        plugin = config / "plugins" / "cache" / "official" / "feature-dev" / "1.0.0"
        manifest = plugin / ".claude-plugin" / "plugin.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            '{"name":"feature-dev","commands":["./bridge/feature-dev.md"]}\n',
            encoding="utf-8",
        )
        (plugin / "bridge").symlink_to(outside, target_is_directory=True)
        inventory = config / "plugins" / "installed_plugins.json"
        inventory.write_text(
            '{"version":2,"plugins":{"feature-dev@official":['
            f'{{"scope":"user","installPath":"{plugin}","version":"1.0.0"}}]}}}}\n',
            encoding="utf-8",
        )

        result = self.run_verify(config_root=config)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ROUTING-SCAN-INCOMPLETE:", result.stdout)
        self.assertNotIn("ROUTING-POLICY: feature-dev", result.stdout)

    def test_plugin_skill_child_symlink_is_not_followed(self) -> None:
        config = self.root / "config"
        outside = self.root / "outside-audit"
        outside.mkdir(parents=True)
        (outside / "SKILL.md").write_text(
            "---\nname: audit\ndescription: 프로젝트 견고성 감사\n---\n",
            encoding="utf-8",
        )
        plugin = config / "plugins" / "cache" / "official" / "audit-pack" / "1.0.0"
        manifest = plugin / ".claude-plugin" / "plugin.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text('{"name":"audit-pack"}\n', encoding="utf-8")
        skills = plugin / "skills"
        skills.mkdir()
        (skills / "audit").symlink_to(outside, target_is_directory=True)
        inventory = config / "plugins" / "installed_plugins.json"
        inventory.write_text(
            '{"version":2,"plugins":{"audit-pack@official":['
            f'{{"scope":"user","installPath":"{plugin}","version":"1.0.0"}}]}}}}\n',
            encoding="utf-8",
        )

        result = self.run_verify(config_root=config)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ROUTING-SCAN-INCOMPLETE:", result.stdout)
        self.assertNotIn("ROUTING-POLICY: audit", result.stdout)

    def test_nul_custom_component_path_is_warn_only(self) -> None:
        plugin = self.root / "plugins" / "cache" / "official" / "bad" / "1.0.0"
        manifest = plugin / ".claude-plugin" / "plugin.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps({"name": "bad", "commands": ["./bad\u0000/path.md"]}),
            encoding="utf-8",
        )
        inventory = self.root / "plugins" / "installed_plugins.json"
        inventory.write_text(
            '{"version":2,"plugins":{"bad@official":['
            f'{{"scope":"user","installPath":"{plugin}","version":"1.0.0"}}]}}}}\n',
            encoding="utf-8",
        )

        result = self.run_verify(config_root=self.root)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ROUTING-SCAN-INCOMPLETE:", result.stdout)
        self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_nul_plugin_path_is_warn_only_for_verifier(self) -> None:
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

        result = self.run_verify(config_root=self.root)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ROUTING-SCAN-INCOMPLETE:", result.stdout)
        self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_routing_diagnostics_escape_control_characters(self) -> None:
        plugin = self.root / "plugins" / "cache" / "evil"
        plugin.mkdir(parents=True)
        manifest = plugin / ".claude-plugin" / "plugin.json"
        manifest.parent.mkdir()
        manifest.write_bytes(b"\xff")
        inventory = self.root / "plugins" / "installed_plugins.json"
        inventory.write_text(
            json.dumps(
                {
                    "version": 2,
                    "plugins": {
                        "evil\nBLOCK: forged\u001b[31m@official": [
                            {"scope": "user", "installPath": str(plugin)}
                        ]
                    },
                }
            ),
            encoding="utf-8",
        )

        result = self.run_verify(config_root=self.root)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("\nBLOCK: forged", result.stdout)
        self.assertNotIn("\x1b", result.stdout)
        self.assertIn("\\u000aBLOCK: forged\\u001b", result.stdout)

    def test_routing_diagnostics_escape_unicode_line_and_paragraph_separators(self) -> None:
        for separator, escaped in (("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
            with self.subTest(separator=escaped):
                config = self.root / ("separator-" + escaped[2:])
                plugin = config / "plugins" / "cache" / "evil"
                plugin.mkdir(parents=True)
                manifest = plugin / ".claude-plugin" / "plugin.json"
                manifest.parent.mkdir()
                manifest.write_bytes(b"\xff")
                inventory = config / "plugins" / "installed_plugins.json"
                inventory.write_text(
                    json.dumps(
                        {
                            "version": 2,
                            "plugins": {
                                f"evil{separator}BLOCK: forged{separator}FAIL: forged@official": [
                                    {"scope": "user", "installPath": str(plugin)}
                                ]
                            },
                        }
                    ),
                    encoding="utf-8",
                )

                result = self.run_verify(config_root=config)

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse(
                    any(line in {"BLOCK: forged", "FAIL: forged@official"} for line in result.stdout.splitlines())
                )
                self.assertIn(escaped, result.stdout)


if __name__ == "__main__":
    unittest.main()
