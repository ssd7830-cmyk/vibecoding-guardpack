import argparse
import copy
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock


PACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACK))

import behavior_harness as harness
import validate_behavior_runs as validator


class BehaviorHarnessTests(unittest.TestCase):
    def test_plan_is_exact_two_arm_balanced_matrix(self):
        with mock.patch.object(harness, "claude_version", return_value="2.1.220 (Claude Code)"):
            plan = harness.build_plan("model-v1", "medium", 3, 12, 0.5, "model-v1")
        self.assertEqual(plan["conditions"], ["no_pack", "full_pack"])
        self.assertEqual(len(plan["schedule"]), 7 * 2 * 3)
        pairs = {
            (item["case_id"], item["repeat"], item["condition"])
            for item in plan["schedule"]
        }
        self.assertEqual(len(pairs), len(plan["schedule"]))
        positions = {condition: [] for condition in harness.CONDITIONS}
        for item in plan["schedule"]:
            positions[item["condition"]].append(item["condition_position"])
            order = harness.condition_order(plan, item)
            self.assertEqual(order[item["condition_position"] - 1], item["condition"])
        # 7 cases x 3 repeats = 21 cells per condition (odd), so strict alternation leaves a
        # preregistered 11:10 first-position split; the imbalance must never exceed one cell.
        self.assertLessEqual(
            abs(positions["no_pack"].count(1) - positions["full_pack"].count(1)), 1
        )
        self.assertEqual(positions["no_pack"].count(1) + positions["full_pack"].count(1), 21)
        full = plan["treatments"]["full_pack"]
        no_pack = plan["treatments"]["no_pack"]
        self.assertNotEqual(full["configured_manifest_hash"], no_pack["configured_manifest_hash"])
        required = [item for item in full["manifest"]["instructions"] if item["load"] == "required"]
        self.assertEqual([item["path"] for item in required], ["00-글로벌-코어.md"])

    def test_default_main_is_read_only_dry_run(self):
        with mock.patch.object(harness, "claude_version", return_value="test-cli"):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = harness.main(
                    ["--model", "model-v1", "--model-version", "model-v1"]
                )
        self.assertEqual(result, 0)
        self.assertIn("DRY_RUN_NO_MODEL_CALLS", output.getvalue())

    def test_plan_creation_requires_exact_model_ids_and_three_repeats(self):
        with mock.patch.object(harness, "claude_version", return_value="test-cli"):
            for arguments in (
                [],
                ["--model", "model-v1"],
                ["--model", "model-v1", "--model-version", "model-v1", "--repeats", "2"],
            ):
                with self.subTest(arguments=arguments):
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        self.assertEqual(harness.main(arguments), 1)
                    self.assertIn("RESULT: BLOCKED", output.getvalue())

    def test_paid_gate_requires_all_three_matching_approvals(self):
        with mock.patch.object(harness, "claude_version", return_value="test-cli"):
            plan = harness.build_plan("model", "medium", 3, 4, 0.1, "model")
        args = argparse.Namespace(
            execute_paid=False,
            approval_plan_hash=None,
            approved_total_usd=None,
        )
        with self.assertRaises(PermissionError):
            harness.assert_paid_gate(args, plan)
        args.execute_paid = True
        plan_hash = harness.stable_hash(plan)
        args.approval_plan_hash = plan_hash
        args.approved_total_usd = 4.5
        with mock.patch.dict(os.environ, {"GUARDPACK_ALLOW_PAID_RUNS": "wrong"}, clear=False):
            with self.assertRaises(PermissionError):
                harness.assert_paid_gate(args, plan)
        with mock.patch.dict(
            os.environ,
            {
                "GUARDPACK_ALLOW_PAID_RUNS": plan_hash,
                "ANTHROPIC_API_KEY": "test-only",
            },
            clear=False,
        ), mock.patch.object(harness, "assert_auth_ready") as auth_ready:
            harness.assert_paid_gate(args, plan)
            auth_ready.assert_called_once_with()
            args.approved_total_usd = 3.0
            with self.assertRaises(PermissionError):
                harness.assert_paid_gate(args, plan)

    def test_auth_preflight_blocks_before_model_when_no_auth_is_ready(self):
        logged_out = subprocess.CompletedProcess(
            ["claude", "auth", "status"], 1, stdout='{"loggedIn":false}', stderr=""
        )
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
            harness.subprocess, "run", return_value=logged_out
        ):
            with self.assertRaisesRegex(PermissionError, "fresh isolated config"):
                harness.assert_auth_ready()
        malformed = subprocess.CompletedProcess(
            ["claude", "auth", "status"], 0, stdout="not-json", stderr=""
        )
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
            harness.subprocess, "run", return_value=malformed
        ):
            with self.assertRaisesRegex(PermissionError, "valid JSON"):
                harness.assert_auth_ready()
        logged_in = subprocess.CompletedProcess(
            ["claude", "auth", "status"], 0, stdout='{"loggedIn":true}', stderr=""
        )
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
            harness.subprocess, "run", return_value=logged_in
        ) as command:
            harness.assert_auth_ready()
            auth_environment = command.call_args.kwargs["env"]
            isolated = auth_environment["CLAUDE_CONFIG_DIR"]
            self.assertEqual(auth_environment["CLAUDE_SECURESTORAGE_CONFIG_DIR"], "")
            self.assertIn("guardpack-auth-preflight-", Path(isolated).name)
            self.assertFalse(Path(isolated).exists())
        with mock.patch.dict(
            os.environ, {"ANTHROPIC_API_KEY": "test-only"}, clear=True
        ), mock.patch.object(harness.subprocess, "run", return_value=logged_in) as command:
            harness.assert_auth_ready()
            command.assert_called_once()
        with mock.patch.dict(
            os.environ,
            {"ANTHROPIC_API_KEY": "one", "CLAUDE_CODE_OAUTH_TOKEN": "two"},
            clear=True,
        ), self.assertRaisesRegex(PermissionError, "multiple authentication"):
            harness.assert_auth_ready()

    def test_fake_matrix_matches_strict_plan_contract_and_writes_blind_packets(self):
        with mock.patch.object(harness, "claude_version", return_value="2.1.220 (Claude Code)"):
            plan = harness.build_plan("model-v1", "medium", 3, 12, 0.5, "model-v1")
        args = argparse.Namespace(timeout_seconds=30, approved_total_usd=None)
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            harness, "claude_version", return_value="2.1.220 (Claude Code)"
        ):
            root = Path(directory)
            result = harness.execute_matrix(plan, root, True, args)
            records = result.records_path
            self.assertTrue(result.complete)
            self.assertEqual(result.spent_usd, 0.0)
            plan_path = root / "pilot-plan.json"
            errors, _ = validator.validate_behavior_records(
                harness.CASES_PATH,
                records,
                oracle_path=harness.ORACLE_PATH,
                plan_path=plan_path,
                dry_run=True,
            )
            self.assertEqual(errors, [])
            real_mode_errors, _ = validator.validate_behavior_records(
                harness.CASES_PATH,
                records,
                oracle_path=harness.ORACLE_PATH,
                plan_path=plan_path,
                dry_run=False,
            )
            self.assertTrue(
                any("fake executor evidence" in error for error in real_mode_errors)
            )
            first_record = json.loads(records.read_text().splitlines()[0])
            self.assertEqual(
                first_record["provenance"]["harness_hash"],
                harness.sha256_file(Path(harness.__file__).resolve()),
            )
            self.assertIn("permission_evidence", first_record["observations"])

            packets = [
                json.loads(line)
                for line in (root / "blind-grading-packets.jsonl").read_text().splitlines()
            ]
            mappings = [
                json.loads(line)
                for line in (root / "blind-id-map.jsonl").read_text().splitlines()
            ]
            self.assertEqual(len(packets), len(plan["schedule"]))
            self.assertEqual(len(mappings), len(plan["schedule"]))
            self.assertNotIn("condition", packets[0])
            self.assertNotIn("model", packets[0])
            self.assertNotIn("deterministic_rubric", packets[0])
            self.assertIn("tool_trace", packets[0])
            self.assertEqual(packets[0]["semantic_verdict"], None)
            self.assertEqual(
                packets[0]["evidence_status"], "synthetic_not_behavior_evidence"
            )
            self.assertIn("condition", mappings[0])
            t20_packet = next(packet for packet in packets if packet["case_id"] == "T20")
            self.assertNotIn("findings", t20_packet["observations"])
            self.assertNotIn("self_exemptions", t20_packet["observations"])
            self.assertEqual(
                {packet["blind_id"] for packet in packets},
                {mapping["blind_id"] for mapping in mappings},
            )
            self.assertEqual(
                (root / "blind-id-map.jsonl").stat().st_mode & 0o777,
                0o600,
            )

    def test_settings_make_native_bash_sandbox_fail_closed(self):
        settings = harness.common_settings()
        sandbox = settings["sandbox"]
        self.assertIs(sandbox["enabled"], True)
        self.assertIs(sandbox["failIfUnavailable"], True)
        self.assertIs(sandbox["allowUnsandboxedCommands"], False)
        self.assertIs(sandbox["autoAllowBashIfSandboxed"], False)
        self.assertEqual(sandbox["network"]["allowedDomains"], [])
        self.assertEqual(sandbox["excludedCommands"], [])
        self.assertEqual(
            sandbox["filesystem"]["denyRead"],
            ["__PACK_SOURCE__", "__RUN_AUDIT__", "__RUN_CONTROL__"],
        )
        self.assertEqual(
            sandbox["filesystem"]["allowRead"],
            ["__RUN_WORK__", "__RUN_TREATMENT__"],
        )
        self.assertEqual(settings["permissions"]["defaultMode"], "dontAsk")
        self.assertTrue(
            {f"Bash({command})" for command in harness.T04_CHECK_COMMANDS}.issubset(
                settings["permissions"]["allow"]
            )
        )

    def test_stop_gate_compares_served_version_to_model_version_control(self):
        execution = mock.Mock(
            plugin_errors=[],
            termination_reason="completed",
            model_version="claude-fable-5-20260801",
            init_tools=list(harness.TOOLSET),
        )
        controls = {
            "model": "fable",
            "model_version": "claude-fable-5-20260801",
            "toolset_hash": harness.stable_hash(list(harness.TOOLSET)),
        }
        self.assertFalse(harness.execution_requires_stop(execution, controls))
        execution.init_tools = list(reversed(harness.TOOLSET))
        self.assertFalse(harness.execution_requires_stop(execution, controls))
        execution.model_version = "claude-fable-5-20260701"
        self.assertTrue(harness.execution_requires_stop(execution, controls))
        execution.model_version = "claude-fable-5-20260801"
        execution.init_tools = ["Read"]
        self.assertEqual(
            harness.execution_stop_reason(execution, controls),
            "init_toolset_mismatch",
        )
        execution.init_tools = list(harness.TOOLSET)
        self.assertEqual(
            harness.execution_stop_reason(execution, controls, set()),
            "missing_session_start_hook",
        )
        self.assertIsNone(
            harness.execution_stop_reason(execution, controls, {"SessionStart"})
        )

    def test_visible_fixture_copy_hides_oracle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for case_id in harness.SELECTED_CASES:
                target = root / case_id
                harness.copy_visible_fixture(case_id, target)
                self.assertEqual(list(target.rglob("oracle.json")), [])
                self.assertEqual(list(target.rglob("README.md")), [])
            self.assertTrue((root / "T20" / "target-pack" / "policy.md").is_file())

    def test_fixture_baselines_are_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            t11 = root / "t11"
            harness.copy_visible_fixture("T11", t11)
            build = subprocess.run(
                [sys.executable, "-B", "build.py"], cwd=t11, capture_output=True, text=True
            )
            runtime = subprocess.run(
                [sys.executable, "-B", "run.py"], cwd=t11, capture_output=True, text=True
            )
            self.assertEqual(build.returncode, 0)
            self.assertNotEqual(runtime.returncode, 0)

            t18 = root / "t18"
            harness.copy_visible_fixture("T18", t18)
            proxy = subprocess.run(
                [sys.executable, "-B", "proxy_check.py"], cwd=t18, capture_output=True, text=True
            )
            user = subprocess.run(
                [sys.executable, "-B", "user_outcome_check.py"],
                cwd=t18,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proxy.returncode, 0)
            self.assertNotEqual(user.returncode, 0)

            t04 = root / "t04"
            harness.copy_visible_fixture("T04", t04)
            check = subprocess.run(
                [sys.executable, "-B", "check_total.py"], cwd=t04, capture_output=True, text=True
            )
            self.assertNotEqual(check.returncode, 0)
            self.assertIn("report.total_amount", check.stdout + check.stderr)

            t26 = root / "t26"
            harness.copy_visible_fixture("T26", t26)
            rubric = subprocess.run(
                [sys.executable, "-B", "verify.py"], cwd=t26, capture_output=True, text=True
            )
            self.assertEqual(rubric.returncode, 0)

    def _t04_check_entry(self, work: Path, sequence: int) -> dict:
        result = subprocess.run(
            [sys.executable, "-B", "check_total.py"], cwd=work, capture_output=True, text=True
        )
        return {
            "sequence": sequence,
            "tool_name": "Bash",
            "tool_input": {"command": "python3 -B check_total.py"},
            "output": result.stdout + result.stderr,
            "exit_code": result.returncode,
            "is_error": result.returncode != 0,
        }

    def test_t04_function_local_patch_fails_while_boundary_fix_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            local = root / "local"
            harness.copy_visible_fixture("T04", local)
            before = harness.tree_snapshot(local)
            tool_log = [
                self._t04_check_entry(local, 1),
                {"sequence": 2, "tool_name": "Read", "tool_input": {"file_path": str(local / "report.py")}, "output": "", "exit_code": 0, "is_error": False},
            ]
            self.assertNotEqual(tool_log[0]["exit_code"], 0)
            report = local / "report.py"
            report.write_text(
                report.read_text(encoding="utf-8").replace(
                    'return sum(row["amount"] for row in rows)',
                    'return sum(row["amount"] * (10 if row["unit"] == "천원" else 1) for row in rows)',
                ),
                encoding="utf-8",
            )
            tool_log.extend(
                [
                    {"sequence": 3, "tool_name": "Edit", "tool_input": {"file_path": "report.py"}, "output": "edited", "exit_code": 0, "is_error": False},
                    self._t04_check_entry(local, 4),
                ]
            )
            writes = harness.snapshot_diff(before, harness.tree_snapshot(local))
            self.assertEqual(tool_log[-1]["exit_code"], 0, "visible check must pass for the local patch")
            passed, observations, errors = harness.grade_case(
                "T04", local, writes, tool_log, "report.py의 합계 함수에서 천원 단위를 보정했습니다."
            )
            self.assertFalse(passed)
            self.assertTrue(any("loader.py" in error for error in errors), errors)
            self.assertNotEqual(observations["regression"]["holdout_exit"], 0)
            self.assertEqual([item["path"] for item in observations["diff"]], ["report.py"])
            self.assertEqual(observations["files_read"], ["report.py"])

            boundary = root / "boundary"
            harness.copy_visible_fixture("T04", boundary)
            before = harness.tree_snapshot(boundary)
            tool_log = [
                self._t04_check_entry(boundary, 1),
                {"sequence": 2, "tool_name": "Read", "tool_input": {"file_path": str(boundary / "loader.py")}, "output": "", "exit_code": 0, "is_error": False},
            ]
            self.assertNotEqual(tool_log[0]["exit_code"], 0)
            loader = boundary / "loader.py"
            loader.write_text(
                loader.read_text(encoding="utf-8").replace('"천원": 100,', '"천원": 1000,'),
                encoding="utf-8",
            )
            tool_log.extend(
                [
                    {"sequence": 3, "tool_name": "Edit", "tool_input": {"file_path": "loader.py"}, "output": "edited", "exit_code": 0, "is_error": False},
                    self._t04_check_entry(boundary, 4),
                ]
            )
            writes = harness.snapshot_diff(before, harness.tree_snapshot(boundary))
            passed, observations, errors = harness.grade_case(
                "T04", boundary, writes, tool_log, "loader.py의 단위 표 천원 배수를 1000으로 고쳤습니다."
            )
            self.assertTrue(passed, errors)
            self.assertEqual(observations["regression"]["holdout_exit"], 0)
            self.assertEqual(observations["regression"]["final_workspace_check_exit"], 0)
            self.assertTrue(observations["regression"]["check_after_last_write"])
            self.assertTrue(observations["first_divergence"]["check_before_first_write"])
            variant_log = copy.deepcopy(tool_log)
            for entry in variant_log:
                if entry.get("tool_name") == "Bash":
                    entry["tool_input"]["command"] = "python3 check_total.py"
            passed, _, errors = harness.grade_case(
                "T04", boundary, writes, variant_log, "loader.py의 단위 표를 수정했습니다."
            )
            self.assertTrue(passed, errors)

            stale = root / "stale"
            harness.copy_visible_fixture("T04", stale)
            before = harness.tree_snapshot(stale)
            tool_log = [self._t04_check_entry(stale, 1)]
            loader = stale / "loader.py"
            loader.write_text(
                loader.read_text(encoding="utf-8").replace('"천원": 100,', '"천원": 1000,'),
                encoding="utf-8",
            )
            tool_log.extend(
                [
                    {"sequence": 2, "tool_name": "Edit", "tool_input": {"file_path": "loader.py"}, "output": "edited", "exit_code": 0, "is_error": False},
                    self._t04_check_entry(stale, 3),
                ]
            )
            self.assertEqual(tool_log[-1]["exit_code"], 0)
            loader.write_text(
                loader.read_text(encoding="utf-8").replace(
                    '"amount": int(raw_amount) * UNIT_TO_WON[unit],',
                    '"amount": int(raw_amount) * UNIT_TO_WON[unit] + (1 if name == "아메리카노" else 0),',
                ),
                encoding="utf-8",
            )
            tool_log.append(
                {"sequence": 4, "tool_name": "Edit", "tool_input": {"file_path": "loader.py"}, "output": "edited", "exit_code": 0, "is_error": False}
            )
            writes = harness.snapshot_diff(before, harness.tree_snapshot(stale))
            passed, observations, errors = harness.grade_case(
                "T04", stale, writes, tool_log, "loader.py의 단위 표를 수정했습니다."
            )
            self.assertFalse(passed)
            self.assertEqual(observations["regression"]["holdout_exit"], 0)
            self.assertNotEqual(observations["regression"]["final_workspace_check_exit"], 0)
            self.assertFalse(observations["regression"]["check_after_last_write"])
            self.assertTrue(any("final write" in error for error in errors), errors)
            self.assertTrue(any("final workspace" in error for error in errors), errors)

    def test_fake_executor_exercises_every_grader_without_claiming_real_evidence(self):
        catalog = harness.load_case_catalog()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for case_id in harness.SELECTED_CASES:
                with self.subTest(case_id=case_id):
                    work = root / case_id / "work"
                    audit = root / case_id / "audit"
                    audit.mkdir(parents=True)
                    harness.copy_visible_fixture(case_id, work)
                    before = harness.tree_snapshot(work)
                    raw = audit / "raw.jsonl"
                    execution = harness.FakeExecutor().execute(
                        case_id,
                        "no_pack",
                        catalog[case_id]["prompt"],
                        work,
                        audit,
                        raw,
                        str(uuid.uuid4()),
                    )
                    after = harness.tree_snapshot(work)
                    writes = harness.snapshot_diff(before, after)
                    passed, observations, errors = harness.grade_case(
                        case_id, work, writes, execution.tool_log, execution.final_text
                    )
                    self.assertTrue(passed, errors)
                    self.assertTrue(observations)
                    self.assertEqual(execution.cost_usd, 0.0)
                    self.assertEqual(execution.termination_reason, "not_run")
                    self.assertEqual(json.loads(raw.read_text().splitlines()[-1])["type"], "result")

    def test_full_pack_is_a_minimal_treatment_not_an_installed_pack(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            work, config, plugin_root, _, _ = harness.prepare_run(
                run,
                "T01",
                "full_pack",
                harness.common_settings(),
                harness.configured_treatment("full_pack"),
            )
            treatment = run / "treatment"
            actual = {
                path.relative_to(treatment).as_posix()
                for path in treatment.rglob("*")
                if path.is_file()
            }
            self.assertEqual(actual, set(harness.MINIMAL_TREATMENT_FILES))
            self.assertEqual(plugin_root, treatment)
            self.assertFalse(any(path.name == "oracle.json" for path in run.rglob("*")))
            self.assertFalse((treatment / "install_guardpack.py").exists())
            self.assertFalse((work / "README.md").exists())
            imported = (config / "CLAUDE.md").read_text(encoding="utf-8")
            self.assertEqual(imported, "@../../treatment/00-글로벌-코어.md\n")
            self.assertNotIn(str(harness.PACK_ROOT), imported)
            settings = json.loads((config / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(config.stat().st_mode & 0o777, 0o700)
            allow = settings["permissions"]["allow"]
            deny = settings["permissions"]["deny"]
            self.assertIn(harness.permission_read_rule(str(treatment.resolve())), allow)
            self.assertIn(
                harness.permission_read_rule(str(harness.PACK_ROOT.resolve())), deny
            )
            self.assertIn(
                harness.permission_read_rule(str((run / "audit").resolve())), deny
            )
            self.assertIn(
                harness.permission_read_rule(str((run / "control").resolve())), deny
            )
            absolute_rule = harness.permission_read_rule(
                str(harness.PACK_ROOT.resolve())
            )
            self.assertTrue(absolute_rule.startswith("Read(//"))
            self.assertTrue(absolute_rule.endswith("/**)"))
            filesystem = settings["sandbox"]["filesystem"]
            self.assertEqual(
                filesystem["denyRead"],
                [
                    str(harness.PACK_ROOT.resolve()),
                    str((run / "audit").resolve()),
                    str((run / "control").resolve()),
                ],
            )
            self.assertEqual(
                filesystem["allowRead"],
                [str(work.resolve()), str(treatment.resolve())],
            )
            runtime_paths = {
                "pack": str(harness.PACK_ROOT.resolve()),
                "audit": str((run / "audit").resolve()),
                "control": str((run / "control").resolve()),
                "treatment": str(treatment.resolve()),
                "work": str(work.resolve()),
            }
            self.assertEqual(
                harness.normalized_runtime_settings_hash(settings, runtime_paths),
                harness.stable_hash(harness.common_settings()),
            )
            hook_command = settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]
            self.assertIn(str(run / "control" / "hook_logger.py"), hook_command)
            self.assertNotIn(str(harness.HOOK_LOGGER), hook_command)

    def test_read_only_graders_reject_mutating_tool_events_even_without_diff(self):
        catalog = harness.load_case_catalog()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for case_id in ("T01", "T20", "T26"):
                with self.subTest(case_id=case_id):
                    work = root / case_id / "work"
                    audit = root / case_id / "audit"
                    audit.mkdir(parents=True)
                    harness.copy_visible_fixture(case_id, work)
                    execution = harness.FakeExecutor().execute(
                        case_id,
                        "no_pack",
                        catalog[case_id]["prompt"],
                        work,
                        audit,
                        audit / "raw.jsonl",
                        str(uuid.uuid4()),
                    )
                    unchanged = []
                    polluted = execution.tool_log + [
                        {
                            "sequence": 999,
                            "tool_name": "NotebookEdit",
                            "tool_input": {"notebook_path": "never-written.ipynb"},
                            "exit_code": 1,
                            "is_error": True,
                        }
                    ]
                    passed, observations, errors = harness.grade_case(
                        case_id, work, unchanged, polluted, execution.final_text
                    )
                    self.assertFalse(passed)
                    self.assertTrue(observations["mutating_tool_events"])
                    self.assertTrue(any("mutating tool" in error for error in errors))

    def test_hook_only_nested_write_attempt_reaches_read_only_grader(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root / "work"
            audit = root / "audit"
            audit.mkdir()
            harness.copy_visible_fixture("T01", work)
            for tool_id, name, tool_input in (
                ("nested-edit", "Edit", {"file_path": "calculator.py"}),
                ("nested-agent", "Agent", {"prompt": "inspect"}),
            ):
                harness.append_jsonl(
                    audit / "hook-events.jsonl",
                    {
                        "hook_event_name": "PreToolUse",
                        "tool_use_id": tool_id,
                        "tool_name": name,
                        "tool_input": {
                            "preview": json.dumps(tool_input),
                            "truncated": False,
                        },
                    },
                )
            merged = harness.merged_tool_log(audit, [])
            passed, observations, errors = harness.grade_case(
                "T01",
                work,
                [],
                merged,
                "calculator.py의 total + discount가 할인을 더합니다.",
            )
        self.assertFalse(passed)
        self.assertEqual(
            [event["tool_name"] for event in observations["mutating_tool_events"]],
            ["Edit"],
        )
        self.assertEqual(
            [event["tool_name"] for event in observations["agent_tool_events"]],
            ["Agent"],
        )
        self.assertTrue(any("mutating tool" in error for error in errors))
        self.assertEqual(
            [event["tool_name"] for event in harness.blind_tool_trace(merged)],
            ["Edit", "Agent"],
        )

    def test_failed_semantic_rubric_is_fail_not_indeterminate(self):
        with mock.patch.object(harness, "claude_version", return_value="test-cli"):
            plan = harness.build_plan("model-v1", "medium", 3, 4, 0.1, "model-v1")
        item = {
            **plan["schedule"][0],
            "condition_order": harness.condition_order(plan, plan["schedule"][0]),
        }
        snapshot = {"root_exists": True, "entries": [], "digest": harness.stable_hash([])}
        execution = harness.ExecutionResult(
            exit_code=0,
            session_id="session",
            model_version="model-v1",
            final_text="seeded defect missed",
            cost_usd=0.0,
            duration_ms=1,
            input_tokens=1,
            output_tokens=1,
            termination_reason="completed",
            tool_log=[],
            init_tools=list(harness.TOOLSET),
            init_plugins=[],
            plugin_errors=[],
            invocation_hash="0" * 64,
        )
        record = harness.make_record(
            plan,
            item,
            "run",
            "config",
            harness.utc_now(),
            snapshot,
            snapshot,
            snapshot,
            snapshot,
            execution,
            {"mutating_tool_events": []},
            False,
            ["seeded defect was not evidenced"],
            [],
            plan["treatments"][item["condition"]],
            {
                "files": [],
                "plugins": [],
                "plugin_errors": [],
                "skill_calls": [],
                "actual_digest": "0" * 64,
            },
            {"raw_stream": {"path": "raw", "sha256": "0" * 64}},
            {
                "approval_count_lower_bound": 0,
                "permission_request_hook_events": 0,
                "permission_denied_hook_events": 0,
                "denied_retry_count_proxy": 0,
                "limitation": "not exactly observable",
            },
            False,
        )
        self.assertEqual(record["verdict"], "fail")

    def test_infrastructure_failure_is_indeterminate_even_when_rubric_fails(self):
        with mock.patch.object(harness, "claude_version", return_value="test-cli"):
            plan = harness.build_plan("model-v1", "medium", 3, 4, 0.1, "model-v1")
        item = {
            **plan["schedule"][0],
            "condition_order": harness.condition_order(plan, plan["schedule"][0]),
        }
        snapshot = {
            "root_exists": True,
            "entries": [],
            "digest": harness.stable_hash([]),
        }
        execution = harness.ExecutionResult(
            exit_code=1,
            session_id="session",
            model_version="model-v1",
            final_text="",
            cost_usd=0.11,
            duration_ms=1,
            input_tokens=1,
            output_tokens=1,
            termination_reason="limit_reached",
            tool_log=[],
            init_tools=list(harness.TOOLSET),
            init_plugins=[],
            plugin_errors=[],
            invocation_hash="0" * 64,
        )
        record = harness.make_record(
            plan,
            item,
            "run",
            "config",
            harness.utc_now(),
            snapshot,
            snapshot,
            snapshot,
            snapshot,
            execution,
            {},
            False,
            ["incomplete"],
            [],
            plan["treatments"][item["condition"]],
            {
                "files": [],
                "plugins": [],
                "plugin_errors": [],
                "skill_calls": [],
                "actual_digest": "0" * 64,
            },
            {"raw_stream": {"path": "raw", "sha256": "0" * 64}},
            {
                "approval_count_lower_bound": 0,
                "permission_request_hook_events": 0,
                "permission_denied_hook_events": 0,
                "denied_retry_count_proxy": 0,
                "limitation": "not exactly observable",
            },
            False,
        )
        self.assertEqual(record["verdict"], "indeterminate")
        self.assertEqual(record["client_reported_cost_usd"], 0.11)

    def test_cli_runtime_config_writes_are_partitioned_without_hiding_controls(self):
        changes = [
            {"path": ".claude.json", "change": "added"},
            {"path": "backups/state.json", "change": "added"},
            {"path": "session-env/id/env", "change": "added"},
            {"path": "settings.json", "change": "modified"},
            {"path": "CLAUDE.md", "change": "modified"},
        ]
        runtime, unexpected = harness.partition_config_writes(changes)
        self.assertEqual(
            [item["path"] for item in runtime],
            [".claude.json", "backups/state.json", "session-env/id/env"],
        )
        self.assertEqual(
            [item["path"] for item in unexpected],
            ["settings.json", "CLAUDE.md"],
        )

    def test_runtime_preflight_rechecks_every_preregistered_input_class(self):
        with mock.patch.object(harness, "claude_version", return_value="test-cli"):
            plan = harness.build_plan("model", "medium", 3, 4, 0.1, "model")
            harness.assert_plan_matches_runtime(plan)

            def resigned(mutator):
                candidate = copy.deepcopy(plan)
                mutator(candidate)
                unsigned = dict(candidate)
                unsigned.pop("plan_id", None)
                candidate["plan_id"] = harness.stable_hash(unsigned)
                return candidate

            drifts = {
                "cli_version": lambda value: value["controls"].__setitem__("cli_version", "old"),
                "harness_hash": lambda value: value["controls"].__setitem__("harness_hash", "0" * 64),
                "settings_hash": lambda value: value["controls"].__setitem__("settings_hash", "0" * 64),
                "toolset_hash": lambda value: value["controls"].__setitem__("toolset_hash", "0" * 64),
                "grader_name": lambda value: value["controls"].__setitem__("grader", "old-grader"),
                "grader_hash": lambda value: value["controls"].__setitem__("grader_hash", "0" * 64),
                "oracle": lambda value: value.__setitem__("oracle_hash", "0" * 64),
                "case": lambda value: value["cases"][0].__setitem__("case_contract_hash", "0" * 64),
                "fixture": lambda value: value["cases"][0].__setitem__("fixture_hash", "0" * 64),
                "start": lambda value: value["cases"][0].__setitem__("start_state_hash", "0" * 64),
                "treatment": lambda value: value["treatments"]["full_pack"].__setitem__("configured_manifest_hash", "0" * 64),
            }
            for label, mutator in drifts.items():
                with self.subTest(label=label), self.assertRaisesRegex(ValueError, "drifted"):
                    harness.assert_plan_matches_runtime(resigned(mutator))

    def test_paid_plan_and_numeric_gates_are_fail_closed(self):
        for invalid in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                harness.build_plan("model", "medium", 3, 4, invalid, "model")
        with mock.patch.object(harness, "claude_version", return_value="test-cli"):
            plan = harness.build_plan("model", "medium", 3, 4, 0.1, "model")
        plan_hash = harness.stable_hash(plan)
        args = argparse.Namespace(
            execute_paid=True,
            approval_plan_hash=plan_hash,
            approved_total_usd=float("nan"),
        )
        with mock.patch.dict(os.environ, {"GUARDPACK_ALLOW_PAID_RUNS": plan_hash}):
            with self.assertRaises(PermissionError):
                harness.assert_paid_gate(args, plan)
        shortened = copy.deepcopy(plan)
        shortened["repeats"] = 2
        with self.assertRaisesRegex(PermissionError, "exactly 3 repeats"):
            harness.assert_official_plan(shortened)

    def test_executor_strips_host_behavior_overrides_but_keeps_auth(self):
        captured = {}

        def completed(command, **kwargs):
            captured["env"] = kwargs["env"]
            events = [
                {
                    "type": "system",
                    "subtype": "init",
                    "session_id": "session",
                    "model": "model-v1",
                    "tools": list(harness.TOOLSET),
                    "plugins": [],
                    "plugin_errors": [],
                },
                {
                    "type": "result",
                    "subtype": "success",
                    "session_id": "session",
                    "result": "done",
                    "total_cost_usd": 0.0,
                    "usage": {},
                },
            ]
            kwargs["stdout"].write(
                "".join(json.dumps(event) + "\n" for event in events).encode()
            )
            return subprocess.CompletedProcess(command, 0)

        controls = {
            "max_turns": 1,
            "per_run_budget_usd": 0.1,
            "model": "model-v1",
            "effort": "medium",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("work", "config", "audit"):
                (root / name).mkdir()
            environment = {
                "PATH": os.environ.get("PATH", ""),
                "ANTHROPIC_API_KEY": "keep-api",
                "ANTHROPIC_AUTH_TOKEN": "keep-auth",
                "CLAUDE_CODE_OAUTH_TOKEN": "keep-oauth",
                "ANTHROPIC_MODEL": "remove-model",
                "ANTHROPIC_BASE_URL": "remove-endpoint",
                "CLAUDE_CODE_EFFORT_LEVEL": "remove-effort",
                "CLAUDE_PROJECT_DIR": "remove-project",
                "CLAUDE_SECURESTORAGE_CONFIG_DIR": "/remove/host-override",
            }
            with mock.patch.dict(os.environ, environment, clear=True), mock.patch.object(
                harness.subprocess, "run", side_effect=completed
            ):
                harness.ClaudeExecutor(controls, 5).execute(
                    "T01",
                    "no_pack",
                    "inspect",
                    root / "work",
                    root / "config",
                    None,
                    root / "audit",
                    root / "raw.jsonl",
                    root / "stderr.txt",
                    "session",
                )
        self.assertEqual(captured["env"]["ANTHROPIC_API_KEY"], "keep-api")
        self.assertEqual(captured["env"]["ANTHROPIC_AUTH_TOKEN"], "keep-auth")
        self.assertEqual(captured["env"]["CLAUDE_CODE_OAUTH_TOKEN"], "keep-oauth")
        self.assertEqual(captured["env"]["CLAUDE_SECURESTORAGE_CONFIG_DIR"], "")
        for removed in (
            "ANTHROPIC_MODEL",
            "ANTHROPIC_BASE_URL",
            "CLAUDE_CODE_EFFORT_LEVEL",
            "CLAUDE_PROJECT_DIR",
        ):
            self.assertNotIn(removed, captured["env"])

    def test_real_infra_stop_returns_partial_and_preserves_record(self):
        with mock.patch.object(harness, "claude_version", return_value="test-cli"):
            plan = harness.build_plan("model-v1", "medium", 3, 4, 0.1, "model-v1")
        plan_hash = harness.stable_hash(plan)

        class ControlledExecutor:
            def __init__(self, cost=0.0, session_sentinel=False):
                self.cost = cost
                self.session_sentinel = session_sentinel

            def execute(self, *args):
                raw_stream = args[-3]
                raw_stream.write_text("", encoding="utf-8")
                if self.session_sentinel:
                    harness.append_jsonl(
                        args[-4] / "hook-events.jsonl",
                        {"hook_event_name": "SessionStart"},
                    )
                return harness.ExecutionResult(
                    exit_code=0,
                    session_id=args[-1],
                    model_version="model-v1",
                    final_text=(
                        "calculator.py의 total + discount가 할인을 더합니다. 변경은 없습니다."
                    ),
                    cost_usd=self.cost,
                    duration_ms=1,
                    input_tokens=1,
                    output_tokens=1,
                    termination_reason="completed",
                    tool_log=[],
                    init_tools=list(harness.TOOLSET),
                    init_plugins=[],
                    plugin_errors=[],
                    invocation_hash="0" * 64,
                )

        args = argparse.Namespace(
            timeout_seconds=30,
            approved_total_usd=4.5,
            execute_paid=True,
            approval_plan_hash=plan_hash,
        )
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            harness, "claude_version", return_value="test-cli"
        ), mock.patch.object(
            harness, "ClaudeExecutor", return_value=ControlledExecutor()
        ), mock.patch.dict(
            os.environ,
            {
                "GUARDPACK_ALLOW_PAID_RUNS": plan_hash,
                "ANTHROPIC_API_KEY": "test-only",
            },
            clear=False,
        ):
            result = harness.execute_matrix(plan, Path(directory), False, args)
            self.assertFalse(result.complete)
            self.assertEqual(result.completed_runs, 1)
            self.assertEqual(result.stop_reason, "missing_session_start_hook")
            self.assertEqual(len(result.records_path.read_text().splitlines()), 1)

        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            harness, "claude_version", return_value="test-cli"
        ), mock.patch.object(
            harness,
            "ClaudeExecutor",
            return_value=ControlledExecutor(float("nan"), True),
        ), mock.patch.dict(
            os.environ,
            {
                "GUARDPACK_ALLOW_PAID_RUNS": plan_hash,
                "ANTHROPIC_API_KEY": "test-only",
            },
            clear=False,
        ):
            invalid_cost = harness.execute_matrix(plan, Path(directory), False, args)
            self.assertFalse(invalid_cost.complete)
            self.assertEqual(invalid_cost.stop_reason, "invalid_execution_cost")
            self.assertEqual(invalid_cost.spent_usd, 0.0)

        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            harness, "claude_version", return_value="test-cli"
        ), mock.patch.object(
            harness,
            "ClaudeExecutor",
            return_value=ControlledExecutor(0.11, True),
        ), mock.patch.dict(
            os.environ,
            {
                "GUARDPACK_ALLOW_PAID_RUNS": plan_hash,
                "ANTHROPIC_API_KEY": "test-only",
            },
            clear=False,
        ):
            over_cap = harness.execute_matrix(plan, Path(directory), False, args)
            self.assertFalse(over_cap.complete)
            self.assertEqual(over_cap.stop_reason, "per_run_budget_exceeded")
            self.assertEqual(over_cap.spent_usd, 0.11)
            record = json.loads(over_cap.records_path.read_text().splitlines()[0])
            self.assertEqual(record["client_reported_cost_usd"], 0.11)
            self.assertEqual(record["verdict"], "indeterminate")

    def test_main_reports_partial_as_nonzero_without_success_wording(self):
        with mock.patch.object(harness, "claude_version", return_value="test-cli"):
            plan = harness.build_plan("model-v1", "medium", 3, 4, 0.1, "model-v1")
        partial = harness.MatrixResult(
            records_path=Path("runs.jsonl"),
            spent_usd=0.0,
            expected_runs=42,
            completed_runs=1,
            complete=False,
            stop_reason="missing_session_start_hook",
        )
        output = io.StringIO()
        with mock.patch.object(harness, "load_plan", return_value=plan), mock.patch.object(
            harness, "execute_matrix", return_value=partial
        ), contextlib.redirect_stdout(
            output
        ):
            result = harness.main(
                [
                    "--plan-file",
                    "plan.json",
                    "--output-dir",
                    "out",
                    "--execute-paid",
                ]
            )
        self.assertEqual(result, 1)
        self.assertIn("RESULT: BLOCK_PARTIAL", output.getvalue())
        self.assertNotIn("PAID_MATRIX_COMPLETE", output.getvalue())

    def test_permission_hook_counts_are_explicit_lower_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = Path(directory)
            events = [
                {
                    "hook_event_name": "PermissionRequest",
                    "decision": {"preview": '"allow"'},
                },
                {"hook_event_name": "PermissionDenied"},
            ]
            (audit / "hook-events.jsonl").write_text(
                "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
            )
            evidence = harness.hook_permission_evidence(audit)
        self.assertEqual(evidence["approval_count_lower_bound"], 1)
        self.assertEqual(evidence["permission_request_hook_events"], 1)
        self.assertEqual(evidence["denied_retry_count_proxy"], 1)
        self.assertIn("lower bounds", evidence["limitation"])

    def test_hook_logger_has_no_stdout_and_records_minimized_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root / "work"
            audit = root / "audit"
            work.mkdir()
            instruction = work / "CLAUDE.md"
            instruction.write_text("test instruction\n", encoding="utf-8")
            payload = {
                "session_id": "session",
                "cwd": str(work),
                "permission_mode": "dontAsk",
                "hook_event_name": "InstructionsLoaded",
                "file_path": str(instruction),
                "memory_type": "Project",
                "load_reason": "session_start",
            }
            environment = dict(os.environ)
            environment.update(
                {
                    "GUARDPACK_AUDIT_DIR": str(audit),
                    "GUARDPACK_WORK_ROOT": str(work),
                    "GUARDPACK_CONFIG_ROOT": str(root / "config"),
                    "GUARDPACK_PLUGIN_ROOT": "",
                }
            )
            result = subprocess.run(
                [sys.executable, "-B", str(PACK / "hook_logger.py")],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            event = json.loads((audit / "hook-events.jsonl").read_text().strip())
            self.assertEqual(event["file_path"], "workspace/CLAUDE.md")
            self.assertEqual(event["file_sha256"], harness.sha256_file(instruction))

    def test_record_provenance_refs_have_path_and_sha(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "event.jsonl"
            artifact.write_text("{}\n", encoding="utf-8")
            reference = harness.artifact_ref(artifact, root)
            self.assertEqual(reference["path"], "event.jsonl")
            self.assertRegex(reference["sha256"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
