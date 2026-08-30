#!/usr/bin/env python3
"""Regression tests for behavior-run record validation."""

from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from pathlib import Path

import sys


PACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACK))

from validate_behavior_runs import (  # noqa: E402
    canonical_hash,
    case_contract_hash,
    validate_behavior_records,
    validate_evaluation_plan,
)


class ValidateBehaviorRunsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="guardpack-run-record-test-")
        self.root = Path(self.temp.name)
        self.cases = PACK / "behavior-fixtures" / "cases.jsonl"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def valid_record(self) -> dict[str, object]:
        cases = [json.loads(line) for line in self.cases.read_text(encoding="utf-8").splitlines()]
        case = next(item for item in cases if item["id"] == "T30")
        return {
            "run_id": "run-T30-candidate-1",
            "case_id": "T30",
            "case_contract_hash": case_contract_hash(case),
            "oracle_hash": hashlib.sha256(
                (PACK / "09-행동-회귀-테스트.md").read_bytes()
            ).hexdigest(),
            "condition": "candidate",
            "condition_artifact_hash": hashlib.sha256(b"candidate-pack").hexdigest(),
            "repeat": 1,
            "condition_order": ["no_pack", "previous", "candidate"],
            "condition_position": 3,
            "started_at": "2026-08-25T12:00:00+09:00",
            "session_id": "session-T30-candidate-1",
            "fresh_session": True,
            "config_root_id": "config-T30-candidate-1",
            "isolated_config_root": True,
            "permission_mode": "fixture-default",
            "toolset_hash": hashlib.sha256(b"toolset").hexdigest(),
            "model": "fixture-model",
            "model_version": "fixture-version",
            "settings_hash": hashlib.sha256(b"settings").hexdigest(),
            "fixture_hash": hashlib.sha256(b"fixture").hexdigest(),
            "start_state_hash": hashlib.sha256(b"start").hexdigest(),
            "end_state_hash": hashlib.sha256(b"end").hexdigest(),
            "state_reset_verified": True,
            "writes": [],
            "tool_log": [],
            "approval_count": 0,
            "denied_retry_count": 0,
            "question_count": 0,
            "duration_ms": 1250,
            "input_tokens": 100,
            "output_tokens": 200,
            "termination_reason": "completed",
            "observations": {
                "invented_defect_hypotheses": False,
                "contract_checks": ["input", "output"],
                "changed_scope": ["fixture/feature.py"],
                "verification": ["fixture test passed"],
                "unnecessary_stop": False
            },
            "user_outcome": "requested fixture behavior passed",
            "verdict": "pass",
            "evidence": ["artifact://fixture-test-log"],
            "grader": "fixed-oracle-v2.2",
            "unverified": []
        }

    def write_record(self, record: dict[str, object]) -> Path:
        path = self.root / "records.jsonl"
        path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
        return path

    def test_valid_record_passes_structural_contract(self) -> None:
        errors, _ = validate_behavior_records(self.cases, self.write_record(self.valid_record()))
        self.assertEqual(errors, [])

    def test_plan_fields_cannot_bypass_plan_validation(self) -> None:
        record = self.valid_record()
        record["record_schema_version"] = "2"
        errors, _ = validate_behavior_records(self.cases, self.write_record(record))
        self.assertTrue(any("plan fields require validation with --plan" in error for error in errors))

    def test_missing_case_observation_fails(self) -> None:
        record = self.valid_record()
        observations = record["observations"]
        assert isinstance(observations, dict)
        del observations["verification"]
        errors, _ = validate_behavior_records(self.cases, self.write_record(record))
        self.assertTrue(any("missing case observations: verification" in error for error in errors))

    def test_pass_with_empty_evidence_fails(self) -> None:
        record = self.valid_record()
        record["evidence"] = []
        errors, _ = validate_behavior_records(self.cases, self.write_record(record))
        self.assertTrue(any("executed verdict requires non-empty evidence" in error for error in errors))

    def test_condition_position_must_match_order(self) -> None:
        record = self.valid_record()
        record["condition_position"] = 1
        errors, _ = validate_behavior_records(self.cases, self.write_record(record))
        self.assertTrue(any("does not match condition_order position" in error for error in errors))

    def test_empty_record_file_fails(self) -> None:
        path = self.root / "empty.jsonl"
        path.write_text("", encoding="utf-8")
        errors, _ = validate_behavior_records(self.cases, path)
        self.assertIn("no behavior run records found", errors)

    def test_invalid_utf8_record_file_fails_without_traceback(self) -> None:
        path = self.root / "invalid-utf8.jsonl"
        path.write_bytes(b"\xff\xfe")
        errors, _ = validate_behavior_records(self.cases, path)
        self.assertTrue(any("could not be read" in error for error in errors))

    def test_duplicate_record_keys_and_nan_observation_fail(self) -> None:
        record = self.valid_record()
        serialized = json.dumps(record, ensure_ascii=False)
        duplicate = serialized.replace(
            '"verdict": "pass"', '"verdict": "fail", "verdict": "pass"', 1
        )
        path = self.root / "duplicate.jsonl"
        path.write_text(duplicate + "\n", encoding="utf-8")
        errors, _ = validate_behavior_records(self.cases, path)
        self.assertTrue(any("duplicate JSON object key: verdict" in error for error in errors))

        observations = record["observations"]
        assert isinstance(observations, dict)
        observations["verification"] = float("nan")
        path = self.root / "nan.jsonl"
        path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
        errors, _ = validate_behavior_records(self.cases, path)
        self.assertTrue(any("non-standard JSON numeric constant: NaN" in error for error in errors))

    def test_malformed_container_types_fail_without_traceback(self) -> None:
        record = self.valid_record()
        record["case_id"] = []
        record["condition_order"] = [["no_pack"], "previous", "candidate"]
        record["verdict"] = []
        record["termination_reason"] = {}
        errors, _ = validate_behavior_records(self.cases, self.write_record(record))
        self.assertTrue(any("references unknown case" in error for error in errors))
        self.assertTrue(any("condition_order must contain" in error for error in errors))
        self.assertTrue(any("invalid verdict" in error for error in errors))

    def test_fail_verdict_still_requires_experimental_evidence(self) -> None:
        record = self.valid_record()
        record["verdict"] = "fail"
        record["fresh_session"] = False
        record["user_outcome"] = ""
        record["evidence"] = []
        observations = record["observations"]
        assert isinstance(observations, dict)
        observations["verification"] = None
        errors, _ = validate_behavior_records(self.cases, self.write_record(record))
        self.assertTrue(any("executed verdict requires fresh" in error for error in errors))
        self.assertTrue(any("executed verdict requires non-empty evidence" in error for error in errors))

    def test_matrix_requires_matched_triplets_with_fixed_controls(self) -> None:
        records = []
        for repeat, condition, position in (
            (1, "no_pack", 1), (2, "previous", 2), (3, "candidate", 3)
        ):
            record = self.valid_record()
            record["run_id"] = f"run-{condition}"
            record["session_id"] = f"session-{condition}"
            record["config_root_id"] = f"config-{condition}"
            record["condition"] = condition
            record["condition_artifact_hash"] = hashlib.sha256(
                f"artifact-{condition}".encode()
            ).hexdigest()
            record["repeat"] = repeat
            record["condition_position"] = position
            record["model"] = f"model-{condition}"
            records.append(record)
        path = self.root / "matrix.jsonl"
        path.write_text(
            "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
            encoding="utf-8",
        )
        errors, _ = validate_behavior_records(
            self.cases, path, require_complete_matrix=True, min_repeats=1
        )
        self.assertTrue(any("incomplete comparison triplet" in error for error in errors))

    def test_complete_matched_matrix_passes_structural_contract(self) -> None:
        cases = [json.loads(line) for line in self.cases.read_text(encoding="utf-8").splitlines()]
        records = []
        order = ["no_pack", "previous", "candidate"]
        for case in cases:
            for position, condition in enumerate(order, 1):
                record = self.valid_record()
                case_id = case["id"]
                record.update(
                    {
                        "run_id": f"run-{case_id}-{condition}",
                        "case_id": case_id,
                        "case_contract_hash": case_contract_hash(case),
                        "condition": condition,
                        "condition_artifact_hash": hashlib.sha256(
                            f"artifact-{case_id}-{condition}".encode()
                        ).hexdigest(),
                        "condition_position": position,
                        "session_id": f"session-{case_id}-{condition}",
                        "config_root_id": f"config-{case_id}-{condition}",
                        "observations": {key: "observed" for key in case["observe"]},
                    }
                )
                records.append(record)
        path = self.root / "complete-matrix.jsonl"
        path.write_text(
            "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
            encoding="utf-8",
        )
        errors, _ = validate_behavior_records(
            self.cases, path, require_complete_matrix=True, min_repeats=1
        )
        self.assertEqual(errors, [])

    def test_oracle_change_invalidates_old_record(self) -> None:
        record = self.valid_record()
        changed_oracle = self.root / "09-changed.md"
        changed_oracle.write_bytes(
            (PACK / "09-행동-회귀-테스트.md").read_bytes() + b"\nchanged rubric\n"
        )
        errors, _ = validate_behavior_records(
            self.cases, self.write_record(record), oracle_path=changed_oracle
        )
        self.assertTrue(any("oracle_hash does not match" in error for error in errors))

    def test_hash_named_fields_require_real_sha256_shape(self) -> None:
        record = self.valid_record()
        record["fixture_hash"] = "fixture-sha256"
        errors, _ = validate_behavior_records(self.cases, self.write_record(record))
        self.assertTrue(any("fixture_hash must be a lowercase SHA-256" in error for error in errors))

    def test_complete_matrix_rejects_control_and_treatment_drift_across_repeats(self) -> None:
        cases = [json.loads(line) for line in self.cases.read_text(encoding="utf-8").splitlines()]
        records = []
        for case in cases:
            for repeat, order in (
                (1, ["no_pack", "previous", "candidate"]),
                (2, ["previous", "candidate", "no_pack"]),
            ):
                for position, condition in enumerate(order, 1):
                    record = self.valid_record()
                    case_id = case["id"]
                    suffix = f"{case_id}-{repeat}-{condition}"
                    record.update(
                        {
                            "run_id": f"run-{suffix}",
                            "case_id": case_id,
                            "case_contract_hash": case_contract_hash(case),
                            "condition": condition,
                            "repeat": repeat,
                            "condition_order": order,
                            "condition_position": position,
                            "session_id": f"session-{suffix}",
                            "config_root_id": f"config-{suffix}",
                            "observations": {key: "observed" for key in case["observe"]},
                            "model": "model-a" if repeat == 1 else "model-b",
                            "fixture_hash": hashlib.sha256(
                                f"fixture-{case_id}-r{repeat}".encode()
                            ).hexdigest(),
                            "start_state_hash": hashlib.sha256(
                                f"start-{case_id}-r{repeat}".encode()
                            ).hexdigest(),
                            "condition_artifact_hash": hashlib.sha256(
                                f"artifact-{case_id}-{condition}-r{repeat}".encode()
                            ).hexdigest(),
                        }
                    )
                    records.append(record)
        path = self.root / "drift-matrix.jsonl"
        path.write_text(
            "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
            encoding="utf-8",
        )
        errors, _ = validate_behavior_records(
            self.cases, path, require_complete_matrix=True, min_repeats=2
        )
        self.assertTrue(any("global controlled field model" in error for error in errors))
        self.assertTrue(any("controlled field fixture_hash" in error for error in errors))
        self.assertTrue(any("treatment across repeats" in error for error in errors))


class PlannedBehaviorRunsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="guardpack-plan-record-test-")
        self.root = Path(self.temp.name)
        self.cases_path = PACK / "behavior-fixtures" / "cases.jsonl"
        self.oracle_path = PACK / "09-행동-회귀-테스트.md"
        self.catalog = {
            item["id"]: item
            for item in (
                json.loads(line)
                for line in self.cases_path.read_text(encoding="utf-8").splitlines()
            )
        }
        self.plan = self.make_plan()
        self.plan_path = self.write_json("pilot-plan.json", self.plan)
        self.records = self.make_records(self.plan)
        self.records_path = self.write_records(self.records)

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def digest(label: str) -> str:
        return hashlib.sha256(label.encode("utf-8")).hexdigest()

    def make_plan(self) -> dict[str, object]:
        no_pack_manifest = {"instructions": [], "plugins": []}
        full_pack_manifest = {
            "instructions": [
                {
                    "path": "00-글로벌-코어.md",
                    "sha256": hashlib.sha256((PACK / "00-글로벌-코어.md").read_bytes()).hexdigest(),
                    "load": "required",
                },
                {
                    "path": "01-비가역-가드.md",
                    "sha256": hashlib.sha256((PACK / "01-비가역-가드.md").read_bytes()).hexdigest(),
                    "load": "allowed_lazy",
                },
            ],
            "plugins": [],
        }
        conditions = ["no_pack", "full_pack"]
        schedule = []
        pilot_cases = ("T01", "T02", "T04", "T11", "T18", "T20", "T26")
        for case_index, case_id in enumerate(pilot_cases):
            for repeat in range(1, 4):
                order = (
                    list(reversed(conditions))
                    if (case_index + repeat) % 2 == 0
                    else conditions
                )
                for position, condition in enumerate(order, 1):
                    schedule.append(
                        {
                            "case_id": case_id,
                            "repeat": repeat,
                            "condition": condition,
                            "condition_position": position,
                        }
                    )
        plan = {
            "schema_version": "1",
            "created_at": "2026-08-25T12:00:00+09:00",
            "oracle_hash": hashlib.sha256(self.oracle_path.read_bytes()).hexdigest(),
            "conditions": conditions,
            "repeats": 3,
            "controls": {
                "cli_version": "test-cli-1",
                "model": "fixture-model",
                "model_version": "fixture-version",
                "effort": "medium",
                "permission_mode": "fixture-default",
                "max_turns": 12,
                "timeout_seconds": 600,
                "per_run_budget_usd": 0.5,
                "toolset_hash": self.digest("toolset"),
                "settings_hash": self.digest("settings"),
                "grader": "fixed-grader",
                "grader_hash": self.digest("grader"),
                "harness_hash": self.digest("harness"),
            },
            "treatments": {
                "no_pack": {
                    "condition": "no_pack",
                    "configured_manifest_hash": canonical_hash(no_pack_manifest),
                    "manifest": no_pack_manifest,
                },
                "full_pack": {
                    "condition": "full_pack",
                    "configured_manifest_hash": canonical_hash(full_pack_manifest),
                    "manifest": full_pack_manifest,
                },
            },
            "cases": [
                {
                    "case_id": case_id,
                    "case_contract_hash": case_contract_hash(self.catalog[case_id]),
                    "fixture_hash": self.digest(f"fixture-{case_id}"),
                    "start_state_hash": self.digest(f"start-{case_id}"),
                    "grader_contract_hash": self.digest(f"grader-{case_id}"),
                }
                for case_id in pilot_cases
            ],
            "schedule": schedule,
            "stop_rule": {"type": "fixed_matrix", "retain_all_outcomes": True},
        }
        plan["plan_id"] = canonical_hash(plan)
        return plan

    def write_json(self, relative: str, value: object) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def artifact(self, relative: str, body: str = "artifact\n") -> dict[str, str]:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(body, encoding="utf-8")
        return {
            "path": relative,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    def manifest_artifact(
        self, condition: str, manifest: dict[str, object]
    ) -> dict[str, str]:
        relative = f"artifacts/manifest-{condition}.json"
        path = self.write_json(relative, manifest)
        return {
            "path": relative,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    def provenance(
        self, plan: dict[str, object], condition: str, run_label: str
    ) -> dict[str, object]:
        controls = plan["controls"]
        treatments = plan["treatments"]
        assert isinstance(controls, dict)
        assert isinstance(treatments, dict)
        treatment = treatments[condition]
        assert isinstance(treatment, dict)
        manifest = treatment["manifest"]
        assert isinstance(manifest, dict)
        return {
            "executor_kind": "real",
            "harness_hash": controls["harness_hash"],
            "cli_version": controls["cli_version"],
            "invocation_hash": self.digest(f"invoke-{run_label}"),
            "exit_code": 0,
            "raw_stream": self.artifact("artifacts/raw.jsonl"),
            "hook_log": self.artifact("artifacts/hooks.jsonl"),
            "before_snapshot": self.artifact("artifacts/before.json"),
            "after_snapshot": self.artifact("artifacts/after.json"),
            "stderr": self.artifact("artifacts/stderr.txt", ""),
            "grader_log": self.artifact("artifacts/grader.json"),
            "configured_treatment_manifest": self.manifest_artifact(
                condition, manifest
            ),
        }

    def loaded(self, plan: dict[str, object], condition: str) -> dict[str, object]:
        treatments = plan["treatments"]
        assert isinstance(treatments, dict)
        treatment = treatments[condition]
        assert isinstance(treatment, dict)
        manifest = treatment["manifest"]
        assert isinstance(manifest, dict)
        instructions = manifest["instructions"]
        assert isinstance(instructions, list)
        files = [
            {
                "path": item["path"],
                "memory_type": "User",
                "load_reason": "include",
                "sha256": item["sha256"],
            }
            for item in instructions
            if item["load"] == "required"
        ]
        payload = {
            "files": files,
            "plugins": [],
            "plugin_errors": [],
            "skill_calls": [],
        }
        return {**payload, "actual_digest": canonical_hash(payload)}

    def make_records(self, plan: dict[str, object]) -> list[dict[str, object]]:
        cases = plan["cases"]
        controls = plan["controls"]
        treatments = plan["treatments"]
        schedule = plan["schedule"]
        assert isinstance(cases, list)
        assert isinstance(controls, dict)
        assert isinstance(treatments, dict)
        assert isinstance(schedule, list)
        plan_cases = {
            str(case["case_id"]): case for case in cases if isinstance(case, dict)
        }
        plan_hash = canonical_hash(plan)
        group_orders: dict[tuple[str, int], list[str]] = {}
        for item in schedule:
            assert isinstance(item, dict)
            key = (str(item["case_id"]), int(item["repeat"]))
            group_orders.setdefault(key, ["", ""])[int(item["condition_position"]) - 1] = str(
                item["condition"]
            )
        records = []
        for item in schedule:
            assert isinstance(item, dict)
            condition = str(item["condition"])
            repeat = int(item["repeat"])
            case_id = str(item["case_id"])
            case = plan_cases[case_id]
            label = f"{case_id}-{repeat}-{condition}"
            loaded = self.loaded(plan, condition)
            treatment = treatments[condition]
            assert isinstance(treatment, dict)
            records.append(
                {
                    "record_schema_version": "2",
                    "evaluation_plan_hash": plan_hash,
                    "treatment_manifest_hash": treatment["configured_manifest_hash"],
                    "loaded_instructions": loaded,
                    "provenance": self.provenance(plan, condition, label),
                    "run_id": f"run-{label}",
                    "case_id": case_id,
                    "case_contract_hash": case["case_contract_hash"],
                    "oracle_hash": plan["oracle_hash"],
                    "condition": condition,
                    "condition_artifact_hash": loaded["actual_digest"],
                    "repeat": repeat,
                    "condition_order": group_orders[(case_id, repeat)],
                    "condition_position": item["condition_position"],
                    "started_at": "2026-08-25T12:00:00+09:00",
                    "session_id": f"session-{label}",
                    "fresh_session": True,
                    "config_root_id": f"config-{label}",
                    "isolated_config_root": True,
                    "permission_mode": controls["permission_mode"],
                    "toolset_hash": controls["toolset_hash"],
                    "model": controls["model"],
                    "model_version": controls["model_version"],
                    "settings_hash": controls["settings_hash"],
                    "fixture_hash": case["fixture_hash"],
                    "start_state_hash": case["start_state_hash"],
                    "end_state_hash": self.digest(f"end-{label}"),
                    "state_reset_verified": True,
                    "writes": [],
                    "tool_log": [{"tool": "Read"}],
                    "approval_count": 0,
                    "denied_retry_count": 0,
                    "question_count": 0,
                    "duration_ms": 1,
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "client_reported_cost_usd": 0.0,
                    "termination_reason": "completed",
                    "observations": {
                        key: "observed" for key in self.catalog[case_id]["observe"]
                    },
                    "user_outcome": "bounded fixture result",
                    "verdict": "pass",
                    "evidence": ["artifacts/raw.jsonl"],
                    "grader": controls["grader"],
                    "unverified": [],
                }
            )
        return records

    def write_records(self, records: list[dict[str, object]]) -> Path:
        path = self.root / "runs.jsonl"
        path.write_text(
            "".join(
                json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
                for record in records
            ),
            encoding="utf-8",
        )
        return path

    def validate(
        self,
        records: list[dict[str, object]] | None = None,
        plan: dict[str, object] | None = None,
        dry_run: bool = False,
    ) -> tuple[list[str], list[str]]:
        selected_plan = plan or self.plan
        plan_path = self.write_json("selected-plan.json", selected_plan)
        records_path = self.write_records(records or self.records)
        return validate_behavior_records(
            self.cases_path,
            records_path,
            oracle_path=self.oracle_path,
            plan_path=plan_path,
            dry_run=dry_run,
        )

    def test_plan_only_validates_exact_two_arm_schedule(self) -> None:
        plan, errors, warnings = validate_evaluation_plan(
            self.cases_path, self.plan_path, oracle_path=self.oracle_path
        )
        self.assertIsNotNone(plan)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])
        self.assertEqual(len(self.plan["schedule"]), 42)

    def test_reduced_or_nonfinite_official_plan_is_rejected(self) -> None:
        reduced = json.loads(json.dumps(self.plan, ensure_ascii=False))
        reduced["repeats"] = 1
        reduced["cases"] = reduced["cases"][:1]
        reduced["schedule"] = [
            item
            for item in reduced["schedule"]
            if item["case_id"] == "T01" and item["repeat"] == 1
        ]
        unsigned = dict(reduced)
        unsigned.pop("plan_id")
        reduced["plan_id"] = canonical_hash(unsigned)
        reduced_path = self.write_json("reduced-plan.json", reduced)
        _, errors, _ = validate_evaluation_plan(
            self.cases_path, reduced_path, oracle_path=self.oracle_path
        )
        self.assertTrue(any("repeats must be exactly 3" in error for error in errors))
        self.assertTrue(any("cases must be exact pilot set" in error for error in errors))

        nonfinite = json.loads(json.dumps(self.plan, ensure_ascii=False))
        nonfinite["controls"]["per_run_budget_usd"] = float("nan")
        unsigned = dict(nonfinite)
        unsigned.pop("plan_id")
        nonfinite["plan_id"] = canonical_hash(unsigned)
        nonfinite_path = self.write_json("nonfinite-plan.json", nonfinite)
        _, errors, _ = validate_evaluation_plan(
            self.cases_path, nonfinite_path, oracle_path=self.oracle_path
        )
        self.assertTrue(
            any(
                "finite number" in error or "non-standard JSON" in error
                for error in errors
            )
        )

        invalid_timeout = json.loads(json.dumps(self.plan, ensure_ascii=False))
        invalid_timeout["controls"]["timeout_seconds"] = 0
        unsigned = dict(invalid_timeout)
        unsigned.pop("plan_id")
        invalid_timeout["plan_id"] = canonical_hash(unsigned)
        invalid_timeout_path = self.write_json(
            "invalid-timeout-plan.json", invalid_timeout
        )
        _, errors, _ = validate_evaluation_plan(
            self.cases_path, invalid_timeout_path, oracle_path=self.oracle_path
        )
        self.assertTrue(any("timeout_seconds" in error for error in errors))

    def test_exact_planned_matrix_passes(self) -> None:
        errors, _ = self.validate()
        self.assertEqual(errors, [])

    def test_planned_record_requires_finite_nonnegative_client_cost(self) -> None:
        for value in (None, -0.01, True, "0"):
            with self.subTest(value=value):
                records = json.loads(json.dumps(self.records, ensure_ascii=False))
                if value is None:
                    records[0].pop("client_reported_cost_usd")
                else:
                    records[0]["client_reported_cost_usd"] = value
                errors, _ = self.validate(records)
                self.assertTrue(
                    any("client_reported_cost_usd" in error for error in errors),
                    errors,
                )

    def test_plan_rejects_legacy_matrix_flags_as_second_source_of_truth(self) -> None:
        errors, _ = validate_behavior_records(
            self.cases_path,
            self.records_path,
            require_complete_matrix=True,
            min_repeats=3,
            oracle_path=self.oracle_path,
            plan_path=self.plan_path,
        )
        self.assertTrue(any("exact matrix source" in error for error in errors))

    def test_missing_extra_and_changed_order_are_rejected(self) -> None:
        missing = self.records[:-1]
        errors, _ = self.validate(missing)
        self.assertTrue(any("planned matrix missing 1" in error for error in errors))

        extra = json.loads(json.dumps(self.records, ensure_ascii=False))
        added = dict(extra[0])
        added.update(
            {
                "run_id": "run-extra",
                "session_id": "session-extra",
                "config_root_id": "config-extra",
                "repeat": 4,
            }
        )
        extra.append(added)
        errors, _ = self.validate(extra)
        self.assertTrue(any("unplanned run record" in error for error in errors))

        changed = json.loads(json.dumps(self.records, ensure_ascii=False))
        changed[0]["condition_order"] = list(reversed(changed[0]["condition_order"]))
        errors, _ = self.validate(changed)
        self.assertTrue(any("changes condition_order" in error for error in errors))

    def test_plan_and_treatment_hash_changes_are_rejected(self) -> None:
        records = json.loads(json.dumps(self.records, ensure_ascii=False))
        records[0]["evaluation_plan_hash"] = self.digest("different-plan")
        records[1]["treatment_manifest_hash"] = self.digest("different-treatment")
        errors, _ = self.validate(records)
        self.assertTrue(any("evaluation_plan_hash does not match" in error for error in errors))
        self.assertTrue(any("treatment_manifest_hash differs" in error for error in errors))

    def test_required_load_and_no_pack_contamination_are_rejected(self) -> None:
        records = json.loads(json.dumps(self.records, ensure_ascii=False))
        full = next(record for record in records if record["condition"] == "full_pack")
        payload = {
            "files": [], "plugins": [], "plugin_errors": [], "skill_calls": []
        }
        full["loaded_instructions"] = {
            **payload, "actual_digest": canonical_hash(payload)
        }
        full["condition_artifact_hash"] = full["loaded_instructions"]["actual_digest"]
        errors, _ = self.validate(records)
        self.assertTrue(any("required instruction was not observed" in error for error in errors))

        records = json.loads(json.dumps(self.records, ensure_ascii=False))
        no_pack = next(record for record in records if record["condition"] == "no_pack")
        full_source = next(record for record in records if record["condition"] == "full_pack")
        loaded_file = full_source["loaded_instructions"]["files"][0]
        payload = {
            "files": [loaded_file], "plugins": [], "plugin_errors": [], "skill_calls": []
        }
        no_pack["loaded_instructions"] = {
            **payload, "actual_digest": canonical_hash(payload)
        }
        no_pack["condition_artifact_hash"] = no_pack["loaded_instructions"]["actual_digest"]
        errors, _ = self.validate(records)
        self.assertTrue(any("loaded unplanned instruction" in error for error in errors))

    def test_allowed_lazy_absence_is_valid_but_unplanned_instruction_is_rejected(self) -> None:
        records = json.loads(json.dumps(self.records, ensure_ascii=False))
        full_records = [record for record in records if record["condition"] == "full_pack"]
        payload = {
            key: value
            for key, value in full_records[1]["loaded_instructions"].items()
            if key != "actual_digest"
        }
        payload["files"].append(
            {
                "path": "project/background.md",
                "memory_type": "Project",
                "load_reason": "session_start",
                "sha256": self.digest("background"),
            }
        )
        full_records[1]["loaded_instructions"] = {
            **payload, "actual_digest": canonical_hash(payload)
        }
        full_records[1]["condition_artifact_hash"] = full_records[1]["loaded_instructions"][
            "actual_digest"
        ]
        errors, _ = self.validate(records)
        self.assertTrue(any("loaded unplanned instruction" in error for error in errors))

    def test_actual_plugin_evidence_rejects_undeclared_fields(self) -> None:
        records = json.loads(json.dumps(self.records, ensure_ascii=False))
        full = next(record for record in records if record["condition"] == "full_pack")
        payload = {
            key: value
            for key, value in full["loaded_instructions"].items()
            if key != "actual_digest"
        }
        payload["plugins"] = [
            {"name": "guardpack", "version": "test", "claimed_loaded": True}
        ]
        full["loaded_instructions"] = {
            **payload, "actual_digest": canonical_hash(payload)
        }
        full["condition_artifact_hash"] = full["loaded_instructions"]["actual_digest"]
        errors, _ = self.validate(records)
        self.assertTrue(any("must contain only name and version" in error for error in errors))

    def test_unplanned_plugin_skill_and_plugin_errors_are_rejected(self) -> None:
        records = json.loads(json.dumps(self.records, ensure_ascii=False))
        no_pack = next(record for record in records if record["condition"] == "no_pack")
        payload = {
            "files": [],
            "plugins": [{"name": "unexpected", "version": "1"}],
            "plugin_errors": [{"message": "failed"}],
            "skill_calls": ["unexpected:skill"],
        }
        no_pack["loaded_instructions"] = {
            **payload,
            "actual_digest": canonical_hash(payload),
        }
        no_pack["condition_artifact_hash"] = no_pack["loaded_instructions"][
            "actual_digest"
        ]
        errors, _ = self.validate(records)
        self.assertTrue(any("loaded unplanned plugin" in error for error in errors))
        self.assertTrue(any("plugin initialization errors" in error for error in errors))
        self.assertTrue(any("loaded unplanned skill" in error for error in errors))

    def test_artifact_hash_path_escape_and_symlink_are_rejected(self) -> None:
        (self.root / "artifacts" / "raw.jsonl").write_text("changed\n", encoding="utf-8")
        errors, _ = self.validate()
        self.assertTrue(any("artifact hash mismatch" in error for error in errors))

        self.setUp_fresh_artifacts()
        records = json.loads(json.dumps(self.records, ensure_ascii=False))
        records[0]["provenance"]["raw_stream"] = {
            "path": "../outside.jsonl", "sha256": self.digest("outside")
        }
        errors, _ = self.validate(records)
        self.assertTrue(any("safe relative POSIX path" in error for error in errors))

        link = self.root / "artifacts" / "raw-link.jsonl"
        link.symlink_to(self.root / "artifacts" / "raw.jsonl")
        records = json.loads(json.dumps(self.records, ensure_ascii=False))
        records[0]["provenance"]["raw_stream"] = {
            "path": "artifacts/raw-link.jsonl",
            "sha256": hashlib.sha256((self.root / "artifacts" / "raw.jsonl").read_bytes()).hexdigest(),
        }
        errors, _ = self.validate(records)
        self.assertTrue(any("contains a symlink" in error for error in errors))

    def setUp_fresh_artifacts(self) -> None:
        (self.root / "artifacts" / "raw.jsonl").write_text("artifact\n", encoding="utf-8")

    def test_fake_not_run_requires_explicit_dry_run(self) -> None:
        records = json.loads(json.dumps(self.records, ensure_ascii=False))
        for record in records:
            record["verdict"] = "not_run"
            record["termination_reason"] = "not_run"
            record["provenance"]["executor_kind"] = "fake"
        errors, _ = self.validate(records, dry_run=True)
        self.assertEqual(errors, [])
        errors, _ = self.validate(records, dry_run=False)
        self.assertTrue(any("fake executor evidence" in error for error in errors))
        self.assertTrue(any("not_run cannot satisfy" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
