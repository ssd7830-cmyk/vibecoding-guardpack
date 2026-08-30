#!/usr/bin/env python3
"""Validate behavior records without grading the model's semantic verdict."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import stat
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from verify_guardpack import RUN_RECORD_REQUIRED, strict_json_loads


LEGACY_CONDITIONS = ("no_pack", "previous", "candidate")
PILOT_CONDITIONS = ("no_pack", "full_pack")
PILOT_CASES = ("T01", "T02", "T04", "T11", "T18", "T20", "T26")
PILOT_REPEATS = 3
PLAN_RECORD_FIELDS = {
    "record_schema_version",
    "evaluation_plan_hash",
    "treatment_manifest_hash",
    "loaded_instructions",
    "provenance",
    "client_reported_cost_usd",
}
VERDICTS = {"pass", "fail", "indeterminate", "not_run"}
TERMINATIONS = {
    "completed", "blocked", "denied", "timeout", "error", "cancelled",
    "limit_reached", "not_run",
}
NONNEGATIVE_INTS = {
    "approval_count", "denied_retry_count", "question_count", "duration_ms",
    "input_tokens", "output_tokens",
}
NONEMPTY_STRINGS = {
    "run_id", "case_id", "started_at", "session_id", "config_root_id",
    "permission_mode", "toolset_hash", "model", "model_version",
    "settings_hash", "fixture_hash", "start_state_hash", "end_state_hash",
    "termination_reason", "grader",
}
HASH_FIELDS = {
    "case_contract_hash", "oracle_hash", "condition_artifact_hash",
    "toolset_hash", "settings_hash", "fixture_hash", "start_state_hash",
    "end_state_hash",
}
PLAN_HASH_FIELDS = {"evaluation_plan_hash", "treatment_manifest_hash"}
PLAN_CONTROL_STRINGS = {
    "cli_version", "model", "model_version", "effort", "permission_mode",
    "grader",
}
PLAN_CONTROL_HASHES = {
    "toolset_hash", "settings_hash", "grader_hash", "harness_hash",
}
ARTIFACT_REF_FIELDS = {"path", "sha256"}
PROVENANCE_ARTIFACT_FIELDS = {
    "raw_stream", "hook_log", "before_snapshot", "after_snapshot", "stderr",
    "grader_log", "configured_treatment_manifest",
}
SAFE_CONDITION = re.compile(r"[a-z][a-z0-9_]{0,31}")
SHA256_HEX = re.compile(r"[0-9a-f]{64}")


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_HEX.fullmatch(value) is not None


def read_jsonl(
    path: Path, label: str
) -> tuple[list[tuple[int, dict[str, Any]]], list[str]]:
    rows: list[tuple[int, dict[str, Any]]] = []
    errors: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        return [], [f"{label} could not be read: {path}: {error}"]
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = strict_json_loads(line)
        except (json.JSONDecodeError, ValueError) as error:
            errors.append(f"{label} line {line_number} is invalid JSON: {error}")
            continue
        if not isinstance(value, dict):
            errors.append(f"{label} line {line_number} is not an object")
            continue
        rows.append((line_number, value))
    return rows, errors


def read_json_object(path: Path, label: str) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        return None, [f"{label} could not be read: {path}: {error}"]
    try:
        value = strict_json_loads(text)
    except (json.JSONDecodeError, ValueError) as error:
        return None, [f"{label} is invalid JSON: {error}"]
    if not isinstance(value, dict):
        return None, [f"{label} is not an object"]
    return value, []


def load_cases(path: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    rows, errors = read_jsonl(path, "case")
    cases: dict[str, dict[str, Any]] = {}
    for line_number, case in rows:
        case_id = case.get("id")
        observations = case.get("observe")
        if not isinstance(case_id, str) or not re.fullmatch(
            r"T(?:0[1-9]|[12][0-9]|30)", case_id
        ):
            errors.append(f"case line {line_number} has an invalid id")
            continue
        if case_id in cases:
            errors.append(f"case id is duplicated: {case_id}")
        if not isinstance(case.get("setup"), str) or not case.get("setup", "").strip():
            errors.append(f"case {case_id} has no setup string")
        if not isinstance(case.get("prompt"), str) or not case.get("prompt", "").strip():
            errors.append(f"case {case_id} has no prompt string")
        if case.get("safe_fixture_only") is not True:
            errors.append(f"case {case_id} does not require a safe isolated fixture")
        valid_observations = (
            isinstance(observations, list)
            and bool(observations)
            and all(isinstance(item, str) and item.strip() for item in observations)
        )
        if not valid_observations or len(observations) != len(set(observations)):
            errors.append(f"case {case_id} has an invalid observation contract")
            continue
        cases[case_id] = case
    expected_ids = {f"T{number:02d}" for number in range(1, 31)}
    missing_ids = sorted(expected_ids - cases.keys())
    if missing_ids:
        errors.append("case catalog missing: " + ", ".join(missing_ids))
    return cases, errors


def is_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def case_contract_hash(case: dict[str, Any]) -> str:
    return canonical_hash(case)


def has_observed_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def safe_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and all(
        part not in ("", ".", "..") for part in path.parts
    )


def hash_regular_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_artifact_ref(
    value: Any, root: Path, label: str, errors: list[str]
) -> None:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return
    if set(value) != ARTIFACT_REF_FIELDS:
        errors.append(f"{label} must contain only path and sha256")
        return
    relative = value.get("path")
    expected_hash = value.get("sha256")
    if not safe_relative_path(relative):
        errors.append(f"{label} path must be a safe relative POSIX path")
        return
    if not valid_sha256(expected_hash):
        errors.append(f"{label} sha256 must be a lowercase SHA-256 hex digest")
        return
    assert isinstance(relative, str)
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        try:
            metadata = current.lstat()
        except OSError as error:
            errors.append(f"{label} artifact could not be inspected: {relative}: {error}")
            return
        if stat.S_ISLNK(metadata.st_mode):
            errors.append(f"{label} artifact path contains a symlink: {relative}")
            return
    try:
        metadata = current.stat()
    except OSError as error:
        errors.append(f"{label} artifact could not be inspected: {relative}: {error}")
        return
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        errors.append(f"{label} artifact is not a single-link regular file: {relative}")
        return
    try:
        actual_hash = hash_regular_file(current)
    except OSError as error:
        errors.append(f"{label} artifact could not be hashed: {relative}: {error}")
        return
    if actual_hash != expected_hash:
        errors.append(f"{label} artifact hash mismatch: {relative}")


def validate_manifest(
    condition: str, treatment: Any, prefix: str, errors: list[str]
) -> dict[str, Any] | None:
    if not isinstance(treatment, dict):
        errors.append(f"{prefix} must be an object")
        return None
    expected_fields = {"condition", "configured_manifest_hash", "manifest"}
    if set(treatment) != expected_fields:
        errors.append(f"{prefix} must contain condition, configured_manifest_hash, manifest")
    if treatment.get("condition") != condition:
        errors.append(f"{prefix} condition does not match its key")
    manifest_hash = treatment.get("configured_manifest_hash")
    manifest = treatment.get("manifest")
    if not valid_sha256(manifest_hash):
        errors.append(f"{prefix} configured_manifest_hash must be a SHA-256 digest")
    if not isinstance(manifest, dict):
        errors.append(f"{prefix} manifest must be an object")
        return None
    if set(manifest) != {"instructions", "plugins"}:
        errors.append(f"{prefix} manifest must contain only instructions and plugins")
        return manifest
    if valid_sha256(manifest_hash) and canonical_hash(manifest) != manifest_hash:
        errors.append(f"{prefix} configured_manifest_hash does not match manifest")

    instructions = manifest.get("instructions")
    seen_paths: set[str] = set()
    if not isinstance(instructions, list):
        errors.append(f"{prefix} manifest instructions must be an array")
    else:
        for index, instruction in enumerate(instructions):
            item = f"{prefix} manifest instruction {index}"
            if not isinstance(instruction, dict) or set(instruction) != {
                "path", "sha256", "load"
            }:
                errors.append(f"{item} must contain path, sha256, load")
                continue
            path = instruction.get("path")
            if not safe_relative_path(path):
                errors.append(f"{item} path must be a safe relative POSIX path")
            elif path in seen_paths:
                errors.append(f"{prefix} duplicates instruction path: {path}")
            else:
                seen_paths.add(path)
            if not valid_sha256(instruction.get("sha256")):
                errors.append(f"{item} sha256 must be a SHA-256 digest")
            if instruction.get("load") not in ("required", "allowed_lazy"):
                errors.append(f"{item} load must be required or allowed_lazy")

    plugins = manifest.get("plugins")
    seen_plugins: set[str] = set()
    if not isinstance(plugins, list):
        errors.append(f"{prefix} manifest plugins must be an array")
    else:
        for index, plugin in enumerate(plugins):
            item = f"{prefix} manifest plugin {index}"
            expected = {"name", "version", "manifest_path", "sha256"}
            if not isinstance(plugin, dict) or set(plugin) != expected:
                errors.append(
                    f"{item} must contain name, version, manifest_path, sha256"
                )
                continue
            name = plugin.get("name")
            if not isinstance(name, str) or not name.strip():
                errors.append(f"{item} name must be a non-empty string")
            elif name in seen_plugins:
                errors.append(f"{prefix} duplicates plugin name: {name}")
            else:
                seen_plugins.add(name)
            if not isinstance(plugin.get("version"), str) or not plugin.get("version", "").strip():
                errors.append(f"{item} version must be a non-empty string")
            if not safe_relative_path(plugin.get("manifest_path")):
                errors.append(f"{item} manifest_path must be a safe relative POSIX path")
            if not valid_sha256(plugin.get("sha256")):
                errors.append(f"{item} sha256 must be a SHA-256 digest")

    if condition == "no_pack" and (instructions or plugins):
        errors.append("no_pack treatment manifest must not configure guardpack artifacts")
    return manifest


def validate_evaluation_plan(
    cases_path: Path,
    plan_path: Path,
    oracle_path: Path | None = None,
) -> tuple[dict[str, Any] | None, list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    cases, case_errors = load_cases(cases_path)
    plan, plan_errors = read_json_object(plan_path, "evaluation plan")
    errors.extend(case_errors)
    errors.extend(plan_errors)
    if plan is None:
        return None, errors, warnings

    required_fields = {
        "schema_version", "plan_id", "created_at", "oracle_hash", "conditions",
        "repeats", "controls", "treatments", "cases", "schedule", "stop_rule",
    }
    if set(plan) != required_fields:
        missing = sorted(required_fields - plan.keys())
        extra = sorted(plan.keys() - required_fields)
        if missing:
            errors.append("evaluation plan missing fields: " + ", ".join(missing))
        if extra:
            errors.append("evaluation plan has undeclared fields: " + ", ".join(extra))
    if plan.get("schema_version") != "1":
        errors.append("evaluation plan schema_version must be '1'")
    if not valid_sha256(plan.get("plan_id")):
        errors.append("evaluation plan plan_id must be the unsigned-plan SHA-256 digest")
    else:
        unsigned_plan = dict(plan)
        unsigned_plan.pop("plan_id", None)
        if canonical_hash(unsigned_plan) != plan.get("plan_id"):
            errors.append("evaluation plan plan_id does not match the unsigned plan")
    if not valid_timestamp(plan.get("created_at")):
        errors.append("evaluation plan created_at must include an ISO 8601 timezone")

    selected_oracle = oracle_path or Path(__file__).resolve().parent / "09-행동-회귀-테스트.md"
    try:
        current_oracle_hash = hashlib.sha256(selected_oracle.read_bytes()).hexdigest()
    except OSError as error:
        current_oracle_hash = ""
        errors.append(f"oracle could not be read: {selected_oracle}: {error}")
    if not valid_sha256(plan.get("oracle_hash")):
        errors.append("evaluation plan oracle_hash must be a SHA-256 digest")
    elif current_oracle_hash and plan.get("oracle_hash") != current_oracle_hash:
        errors.append("evaluation plan oracle_hash does not match the current 09 oracle")

    raw_conditions = plan.get("conditions")
    conditions: tuple[str, ...] = ()
    if raw_conditions != list(PILOT_CONDITIONS):
        errors.append("evaluation plan conditions must be exact no_pack/full_pack pilot arms")
    else:
        conditions = PILOT_CONDITIONS

    repeats = plan.get("repeats")
    if repeats != PILOT_REPEATS:
        errors.append(f"evaluation plan repeats must be exactly {PILOT_REPEATS}")
        repeats = 0

    controls = plan.get("controls")
    control_fields = (
        PLAN_CONTROL_STRINGS
        | PLAN_CONTROL_HASHES
        | {"max_turns", "timeout_seconds", "per_run_budget_usd"}
    )
    if not isinstance(controls, dict):
        errors.append("evaluation plan controls must be an object")
        controls = {}
    elif set(controls) != control_fields:
        errors.append("evaluation plan controls do not match the declared control contract")
    for field in PLAN_CONTROL_STRINGS:
        if not isinstance(controls.get(field), str) or not controls.get(field, "").strip():
            errors.append(f"evaluation plan control {field} must be a non-empty string")
    for field in PLAN_CONTROL_HASHES:
        if not valid_sha256(controls.get(field)):
            errors.append(f"evaluation plan control {field} must be a SHA-256 digest")
    if not isinstance(controls.get("max_turns"), int) or isinstance(
        controls.get("max_turns"), bool
    ) or controls.get("max_turns", 0) < 1:
        errors.append("evaluation plan control max_turns must be an integer >= 1")
    if not isinstance(controls.get("timeout_seconds"), int) or isinstance(
        controls.get("timeout_seconds"), bool
    ) or controls.get("timeout_seconds", 0) < 1:
        errors.append("evaluation plan control timeout_seconds must be an integer >= 1")
    budget = controls.get("per_run_budget_usd")
    if (
        not isinstance(budget, (int, float))
        or isinstance(budget, bool)
        or not math.isfinite(float(budget))
        or budget <= 0
    ):
        errors.append("evaluation plan control per_run_budget_usd must be a finite number > 0")

    treatments = plan.get("treatments")
    if not isinstance(treatments, dict):
        errors.append("evaluation plan treatments must be an object")
        treatments = {}
    elif set(treatments) != set(conditions):
        errors.append("evaluation plan treatment keys must exactly match conditions")
    configured_hashes: list[str] = []
    for condition in conditions:
        treatment = treatments.get(condition)
        validate_manifest(condition, treatment, f"treatment {condition}", errors)
        if isinstance(treatment, dict) and valid_sha256(
            treatment.get("configured_manifest_hash")
        ):
            configured_hashes.append(treatment["configured_manifest_hash"])
    if len(configured_hashes) == len(conditions) and len(set(configured_hashes)) != len(conditions):
        errors.append("evaluation plan conditions must identify distinct configured treatments")

    raw_plan_cases = plan.get("cases")
    plan_cases: dict[str, dict[str, Any]] = {}
    if not isinstance(raw_plan_cases, list) or not raw_plan_cases:
        errors.append("evaluation plan cases must be a non-empty array")
        raw_plan_cases = []
    case_fields = {
        "case_id", "case_contract_hash", "fixture_hash", "start_state_hash",
        "grader_contract_hash",
    }
    for index, item in enumerate(raw_plan_cases):
        prefix = f"evaluation plan case {index}"
        if not isinstance(item, dict) or set(item) != case_fields:
            errors.append(f"{prefix} does not match the case contract")
            continue
        case_id = item.get("case_id")
        if not isinstance(case_id, str) or case_id not in cases:
            errors.append(f"{prefix} references unknown case: {case_id!r}")
            continue
        if case_id in plan_cases:
            errors.append(f"evaluation plan duplicates case: {case_id}")
            continue
        plan_cases[case_id] = item
        if item.get("case_contract_hash") != case_contract_hash(cases[case_id]):
            errors.append(f"evaluation plan case_contract_hash does not match {case_id}")
        for field in ("fixture_hash", "start_state_hash", "grader_contract_hash"):
            if not valid_sha256(item.get(field)):
                errors.append(f"{prefix} {field} must be a SHA-256 digest")
    if set(plan_cases) != set(PILOT_CASES):
        missing = sorted(set(PILOT_CASES) - set(plan_cases))
        extra = sorted(set(plan_cases) - set(PILOT_CASES))
        errors.append(
            "evaluation plan cases must be exact pilot set; "
            f"missing={missing}, extra={extra}"
        )

    schedule = plan.get("schedule")
    if not isinstance(schedule, list):
        errors.append("evaluation plan schedule must be an array")
        schedule = []
    schedule_fields = {"case_id", "repeat", "condition", "condition_position"}
    schedule_keys: set[tuple[str, str, int]] = set()
    schedule_groups: defaultdict[tuple[str, int], dict[str, int]] = defaultdict(dict)
    for index, item in enumerate(schedule):
        prefix = f"evaluation plan schedule item {index}"
        if not isinstance(item, dict) or set(item) != schedule_fields:
            errors.append(f"{prefix} does not match the schedule contract")
            continue
        case_id = item.get("case_id")
        condition = item.get("condition")
        repeat = item.get("repeat")
        position = item.get("condition_position")
        if not isinstance(case_id, str) or case_id not in plan_cases:
            errors.append(f"{prefix} references unselected case: {case_id!r}")
        if not isinstance(condition, str) or condition not in conditions:
            errors.append(f"{prefix} references undeclared condition: {condition!r}")
        if not isinstance(repeat, int) or isinstance(repeat, bool) or not 1 <= repeat <= repeats:
            errors.append(f"{prefix} repeat is outside the fixed plan")
        if not isinstance(position, int) or isinstance(position, bool) or not 1 <= position <= len(conditions):
            errors.append(f"{prefix} condition_position is outside the condition order")
        if isinstance(case_id, str) and isinstance(condition, str) and isinstance(repeat, int):
            key = (case_id, condition, repeat)
            if key in schedule_keys:
                errors.append(f"evaluation plan schedule duplicates cell: {key}")
            schedule_keys.add(key)
            if isinstance(position, int):
                schedule_groups[(case_id, repeat)][condition] = position

    expected_keys = {
        (case_id, condition, repeat)
        for case_id in plan_cases
        for repeat in range(1, repeats + 1)
        for condition in conditions
    }
    missing_schedule = sorted(expected_keys - schedule_keys)
    extra_schedule = sorted(schedule_keys - expected_keys)
    if missing_schedule:
        errors.append(f"evaluation plan schedule missing {len(missing_schedule)} cell(s)")
    if extra_schedule:
        errors.append(f"evaluation plan schedule has {len(extra_schedule)} extra cell(s)")
    for group, positions in sorted(schedule_groups.items()):
        if set(positions) != set(conditions) or set(positions.values()) != set(
            range(1, len(conditions) + 1)
        ):
            errors.append(f"evaluation plan schedule group {group} is not a full order")

    stop_rule = plan.get("stop_rule")
    if stop_rule != {"type": "fixed_matrix", "retain_all_outcomes": True}:
        errors.append("evaluation plan stop_rule must retain every fixed-matrix outcome")

    for case_id in sorted(plan_cases):
        orders = {
            tuple(
                condition
                for condition, _ in sorted(
                    schedule_groups.get((case_id, repeat), {}).items(),
                    key=lambda pair: pair[1],
                )
            )
            for repeat in range(1, repeats + 1)
        }
        if repeats > 1 and len(orders) == 1:
            warnings.append(
                f"{case_id} planned repeats all use one condition order; order effects are not counterbalanced"
            )
    return plan, errors, warnings


def validate_loaded_instructions(
    record: dict[str, Any],
    treatment: dict[str, Any],
    all_treatments: dict[str, Any],
    prefix: str,
    errors: list[str],
) -> None:
    loaded = record.get("loaded_instructions")
    if not isinstance(loaded, dict):
        errors.append(f"{prefix} loaded_instructions must be an object")
        return
    expected_fields = {"files", "plugins", "plugin_errors", "skill_calls", "actual_digest"}
    if set(loaded) != expected_fields:
        errors.append(f"{prefix} loaded_instructions does not match the actual-load contract")
        return
    actual_digest = loaded.get("actual_digest")
    actual_payload = {key: value for key, value in loaded.items() if key != "actual_digest"}
    if not valid_sha256(actual_digest):
        errors.append(f"{prefix} loaded_instructions actual_digest must be a SHA-256 digest")
    elif canonical_hash(actual_payload) != actual_digest:
        errors.append(f"{prefix} loaded_instructions actual_digest does not match its payload")
    if record.get("condition_artifact_hash") != actual_digest:
        errors.append(f"{prefix} condition_artifact_hash does not match actual loaded instructions")

    files = loaded.get("files")
    actual_files: dict[str, str] = {}
    if not isinstance(files, list):
        errors.append(f"{prefix} loaded_instructions files must be an array")
        files = []
    for index, item in enumerate(files):
        label = f"{prefix} loaded instruction file {index}"
        expected = {"path", "memory_type", "load_reason", "sha256"}
        if not isinstance(item, dict) or set(item) != expected:
            errors.append(f"{label} must contain path, memory_type, load_reason, sha256")
            continue
        path = item.get("path")
        if not safe_relative_path(path):
            errors.append(f"{label} path must be a safe logical POSIX path")
            continue
        if path in actual_files:
            errors.append(f"{prefix} duplicates loaded instruction path: {path}")
        if not valid_sha256(item.get("sha256")):
            errors.append(f"{label} sha256 must be a SHA-256 digest")
        else:
            actual_files[path] = item["sha256"]
        for field in ("memory_type", "load_reason"):
            if not isinstance(item.get(field), str) or not item.get(field, "").strip():
                errors.append(f"{label} {field} must be a non-empty string")

    for field in ("plugins", "plugin_errors", "skill_calls"):
        if not isinstance(loaded.get(field), list):
            errors.append(f"{prefix} loaded_instructions {field} must be an array")

    manifest = treatment.get("manifest", {}) if isinstance(treatment, dict) else {}
    configured = {
        item.get("path"): item
        for item in manifest.get("instructions", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    for path, item in configured.items():
        if item.get("load") == "required" and path not in actual_files:
            errors.append(f"{prefix} required instruction was not observed as loaded: {path}")
    for path, digest in actual_files.items():
        if path not in configured:
            errors.append(f"{prefix} loaded unplanned instruction: {path}")
        elif digest != configured[path].get("sha256"):
            errors.append(f"{prefix} loaded instruction hash differs from configured manifest: {path}")

    expected_plugins = {
        item.get("name"): item
        for item in manifest.get("plugins", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    actual_plugins: dict[str, dict[str, Any]] = {}
    raw_plugins = loaded.get("plugins")
    if isinstance(raw_plugins, list):
        for index, plugin in enumerate(raw_plugins):
            label = f"{prefix} loaded plugin {index}"
            if not isinstance(plugin, dict) or set(plugin) != {"name", "version"}:
                errors.append(f"{label} must contain only name and version")
                continue
            name = plugin.get("name")
            version = plugin.get("version")
            if not isinstance(name, str) or not name.strip():
                errors.append(f"{label} name must be a non-empty string")
                continue
            if not isinstance(version, str) or not version.strip():
                errors.append(f"{label} version must be a non-empty string")
            if name in actual_plugins:
                errors.append(f"{prefix} duplicates loaded plugin: {name}")
            actual_plugins[name] = plugin
    for name, expected in expected_plugins.items():
        actual = actual_plugins.get(name)
        if actual is None:
            errors.append(f"{prefix} configured plugin was not observed: {name}")
        elif actual.get("version") != expected.get("version"):
            errors.append(f"{prefix} loaded plugin version differs from manifest: {name}")
    for name in actual_plugins:
        if name not in expected_plugins:
            errors.append(f"{prefix} loaded unplanned plugin: {name}")

    plugin_errors = loaded.get("plugin_errors")
    if isinstance(plugin_errors, list) and plugin_errors:
        errors.append(f"{prefix} observed plugin initialization errors")

    configured_skill_names = {
        PurePosixPath(path).parent.name
        for path in configured
        if path.startswith("skills/") and path.endswith("/SKILL.md")
    }
    skill_calls = loaded.get("skill_calls")
    if isinstance(skill_calls, list):
        for index, skill in enumerate(skill_calls):
            if not isinstance(skill, str) or not skill.strip():
                errors.append(f"{prefix} skill call {index} must be a non-empty string")
                continue
            short_name = skill.rsplit(":", 1)[-1]
            if short_name not in configured_skill_names:
                errors.append(f"{prefix} loaded unplanned skill: {skill}")


def validate_provenance(
    record: dict[str, Any],
    controls: dict[str, Any],
    records_root: Path,
    expected_treatment_hash: str,
    dry_run: bool,
    prefix: str,
    errors: list[str],
) -> None:
    provenance = record.get("provenance")
    required = {
        "executor_kind", "harness_hash", "cli_version", "invocation_hash",
        "exit_code", *PROVENANCE_ARTIFACT_FIELDS,
    }
    if not isinstance(provenance, dict):
        errors.append(f"{prefix} provenance must be an object")
        return
    if set(provenance) != required:
        errors.append(f"{prefix} provenance does not match the provenance contract")
        return
    executor_kind = provenance.get("executor_kind")
    if executor_kind not in ("real", "fake"):
        errors.append(f"{prefix} provenance executor_kind must be real or fake")
    if dry_run:
        if executor_kind != "fake":
            errors.append(f"{prefix} dry-run records require executor_kind fake")
        if record.get("verdict") != "not_run" or record.get("termination_reason") != "not_run":
            errors.append(f"{prefix} dry-run records must be explicitly not_run")
    else:
        if executor_kind == "fake":
            errors.append(f"{prefix} fake executor evidence is allowed only in explicit dry-run mode")
        if record.get("verdict") == "not_run":
            errors.append(f"{prefix} not_run cannot satisfy a planned real-execution cell")
    if provenance.get("harness_hash") != controls.get("harness_hash"):
        errors.append(f"{prefix} provenance harness_hash differs from the evaluation plan")
    if provenance.get("cli_version") != controls.get("cli_version"):
        errors.append(f"{prefix} provenance cli_version differs from the evaluation plan")
    if not valid_sha256(provenance.get("invocation_hash")):
        errors.append(f"{prefix} provenance invocation_hash must be a SHA-256 digest")
    exit_code = provenance.get("exit_code")
    if exit_code is not None and (
        not isinstance(exit_code, int) or isinstance(exit_code, bool)
    ):
        errors.append(f"{prefix} provenance exit_code must be an integer or null")
    for field in PROVENANCE_ARTIFACT_FIELDS:
        validate_artifact_ref(
            provenance.get(field), records_root, f"{prefix} provenance {field}", errors
        )
    manifest_ref = provenance.get("configured_treatment_manifest")
    if isinstance(manifest_ref, dict) and safe_relative_path(manifest_ref.get("path")):
        manifest_path = records_root / manifest_ref["path"]
        manifest_value, manifest_errors = read_json_object(
            manifest_path, f"{prefix} configured treatment manifest"
        )
        errors.extend(manifest_errors)
        if manifest_value is not None and canonical_hash(manifest_value) != expected_treatment_hash:
            errors.append(
                f"{prefix} configured treatment manifest content differs from the evaluation plan"
            )


def validate_behavior_records(
    cases_path: Path,
    records_path: Path,
    require_complete_matrix: bool = False,
    min_repeats: int = 1,
    oracle_path: Path | None = None,
    plan_path: Path | None = None,
    dry_run: bool = False,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    cases, case_errors = load_cases(cases_path)
    errors.extend(case_errors)

    plan: dict[str, Any] | None = None
    if plan_path is not None:
        plan, plan_errors, plan_warnings = validate_evaluation_plan(
            cases_path, plan_path, oracle_path=oracle_path
        )
        errors.extend(plan_errors)
        warnings.extend(plan_warnings)
        if plan is None or plan_errors:
            return errors, warnings
        if require_complete_matrix or min_repeats != 1:
            errors.append(
                "--plan is the exact matrix source; legacy complete-matrix flags cannot be combined"
            )
    elif dry_run:
        errors.append("dry_run requires an evaluation plan")

    rows, record_errors = read_jsonl(records_path, "record")
    errors.extend(record_errors)
    if not rows:
        errors.append("no behavior run records found")
    if min_repeats < 1:
        errors.append("min_repeats must be at least 1")

    selected_oracle = oracle_path or Path(__file__).resolve().parent / "09-행동-회귀-테스트.md"
    try:
        current_oracle_hash = hashlib.sha256(selected_oracle.read_bytes()).hexdigest()
    except OSError as error:
        current_oracle_hash = ""
        errors.append(f"oracle could not be read: {selected_oracle}: {error}")

    active_conditions = tuple(plan["conditions"]) if plan is not None else LEGACY_CONDITIONS
    plan_hash = canonical_hash(plan) if plan is not None else ""
    plan_cases = {
        item["case_id"]: item for item in plan.get("cases", [])
    } if plan is not None else {}
    plan_treatments = plan.get("treatments", {}) if plan is not None else {}
    plan_controls = plan.get("controls", {}) if plan is not None else {}
    planned_schedule: dict[tuple[str, str, int], int] = {}
    planned_orders: defaultdict[tuple[str, int], dict[int, str]] = defaultdict(dict)
    if plan is not None:
        for item in plan.get("schedule", []):
            key = (item["case_id"], item["condition"], item["repeat"])
            planned_schedule[key] = item["condition_position"]
            planned_orders[(item["case_id"], item["repeat"])][
                item["condition_position"]
            ] = item["condition"]

    run_ids: set[str] = set()
    session_ids: set[str] = set()
    config_root_ids: set[str] = set()
    run_keys: set[tuple[str, str, int]] = set()
    group_orders: dict[tuple[str, int], tuple[str, ...]] = {}
    group_positions: defaultdict[tuple[str, int], set[int]] = defaultdict(set)
    orders_by_case: defaultdict[str, set[tuple[str, ...]]] = defaultdict(set)
    group_records: defaultdict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)

    for line_number, record in rows:
        prefix = f"record line {line_number}"
        missing = sorted(RUN_RECORD_REQUIRED - record.keys())
        if missing:
            errors.append(f"{prefix} missing fields: {', '.join(missing)}")
        allowed_fields = RUN_RECORD_REQUIRED | PLAN_RECORD_FIELDS
        extra = sorted(record.keys() - allowed_fields)
        if extra:
            errors.append(f"{prefix} has undeclared fields: {', '.join(extra)}")
        if plan is not None:
            missing_plan = sorted(PLAN_RECORD_FIELDS - record.keys())
            if missing_plan:
                errors.append(f"{prefix} missing plan fields: {', '.join(missing_plan)}")
        elif record.keys() & PLAN_RECORD_FIELDS:
            errors.append(f"{prefix} plan fields require validation with --plan")

        for field in NONEMPTY_STRINGS:
            if not isinstance(record.get(field), str) or not record.get(field, "").strip():
                errors.append(f"{prefix} field {field} must be a non-empty string")
        for field in HASH_FIELDS:
            if not valid_sha256(record.get(field)):
                errors.append(f"{prefix} field {field} must be a lowercase SHA-256 hex digest")
        if current_oracle_hash and record.get("oracle_hash") != current_oracle_hash:
            errors.append(f"{prefix} oracle_hash does not match the current 09 oracle")
        if not valid_timestamp(record.get("started_at")):
            errors.append(f"{prefix} started_at must be an ISO 8601 timestamp with timezone")

        case_id = record.get("case_id")
        condition = record.get("condition")
        repeat = record.get("repeat")
        position = record.get("condition_position")
        order = record.get("condition_order")
        if not isinstance(case_id, str) or case_id not in cases:
            errors.append(f"{prefix} references unknown case: {case_id!r}")
        elif record.get("case_contract_hash") != case_contract_hash(cases[case_id]):
            errors.append(f"{prefix} case_contract_hash does not match current {case_id}")
        if not isinstance(condition, str) or condition not in active_conditions:
            errors.append(f"{prefix} has invalid condition: {condition!r}")
        if not isinstance(repeat, int) or isinstance(repeat, bool) or repeat < 1:
            errors.append(f"{prefix} repeat must be an integer >= 1")
        if not isinstance(position, int) or isinstance(position, bool) or not 1 <= position <= len(active_conditions):
            errors.append(f"{prefix} condition_position must be 1..{len(active_conditions)}")
        valid_order = (
            isinstance(order, list)
            and len(order) == len(active_conditions)
            and all(isinstance(item, str) for item in order)
            and set(order) == set(active_conditions)
        )
        if not valid_order:
            errors.append(f"{prefix} condition_order must contain each comparison condition once")
        elif isinstance(position, int) and 1 <= position <= len(active_conditions) and condition in active_conditions:
            if order[position - 1] != condition:
                errors.append(f"{prefix} condition does not match condition_order position")

        for field in ("fresh_session", "isolated_config_root", "state_reset_verified"):
            if not isinstance(record.get(field), bool):
                errors.append(f"{prefix} field {field} must be boolean")
        for field in NONNEGATIVE_INTS:
            if not is_nonnegative_int(record.get(field)):
                errors.append(f"{prefix} field {field} must be an integer >= 0")
        for field in ("writes", "tool_log", "evidence", "unverified"):
            if not isinstance(record.get(field), list):
                errors.append(f"{prefix} field {field} must be an array")
        for field in ("evidence", "unverified"):
            values = record.get(field)
            if isinstance(values, list) and any(
                not isinstance(item, str) or not item.strip() for item in values
            ):
                errors.append(f"{prefix} field {field} must contain non-empty strings")
        if not isinstance(record.get("user_outcome"), str):
            errors.append(f"{prefix} user_outcome must be a string")
        verdict = record.get("verdict")
        if not isinstance(verdict, str) or verdict not in VERDICTS:
            errors.append(f"{prefix} has invalid verdict: {verdict!r}")
        termination = record.get("termination_reason")
        if not isinstance(termination, str) or termination not in TERMINATIONS:
            errors.append(f"{prefix} has invalid termination_reason: {termination!r}")

        observations = record.get("observations")
        expected_observations = cases.get(case_id, {}).get("observe", []) if isinstance(case_id, str) else []
        if not isinstance(observations, dict):
            errors.append(f"{prefix} observations must be an object")
        else:
            absent = [key for key in expected_observations if key not in observations]
            if absent:
                errors.append(f"{prefix} missing case observations: {', '.join(absent)}")

        if verdict in ("pass", "fail"):
            if not all(
                record.get(field) is True
                for field in ("fresh_session", "isolated_config_root", "state_reset_verified")
            ):
                errors.append(f"{prefix} executed verdict requires fresh isolated verified state")
            outcome = record.get("user_outcome")
            if not isinstance(outcome, str) or not outcome.strip():
                errors.append(f"{prefix} executed verdict requires a non-empty user_outcome")
            evidence = record.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                errors.append(f"{prefix} executed verdict requires non-empty evidence")
            if isinstance(observations, dict):
                empty = [
                    key for key in expected_observations
                    if key in observations and not has_observed_value(observations[key])
                ]
                if empty:
                    errors.append(
                        f"{prefix} executed verdict has empty case observations: {', '.join(empty)}"
                    )
        if verdict == "pass" and termination != "completed":
            errors.append(f"{prefix} pass requires termination_reason completed")
        if verdict == "fail" and termination == "not_run":
            errors.append(f"{prefix} fail cannot use termination_reason not_run")
        if verdict == "indeterminate" and not record.get("unverified"):
            errors.append(f"{prefix} indeterminate requires a non-empty unverified list")
        if verdict == "not_run" and termination != "not_run":
            errors.append(f"{prefix} not_run requires termination_reason not_run")

        for value, seen, label in (
            (record.get("run_id"), run_ids, "run_id"),
            (record.get("session_id"), session_ids, "session_id"),
            (record.get("config_root_id"), config_root_ids, "config_root_id"),
        ):
            if isinstance(value, str) and value:
                if value in seen:
                    errors.append(f"{prefix} duplicates {label}: {value}")
                seen.add(value)

        if plan is not None:
            cost = record.get("client_reported_cost_usd")
            if (
                not isinstance(cost, (int, float))
                or isinstance(cost, bool)
                or not math.isfinite(float(cost))
                or float(cost) < 0
            ):
                errors.append(
                    f"{prefix} client_reported_cost_usd must be a finite number >= 0"
                )
            for field in PLAN_HASH_FIELDS:
                if not valid_sha256(record.get(field)):
                    errors.append(f"{prefix} field {field} must be a lowercase SHA-256 hex digest")
            if record.get("record_schema_version") != "2":
                errors.append(f"{prefix} record_schema_version must be '2' in plan mode")
            if record.get("evaluation_plan_hash") != plan_hash:
                errors.append(f"{prefix} evaluation_plan_hash does not match the fixed plan")
            selected_case = plan_cases.get(case_id) if isinstance(case_id, str) else None
            if selected_case is None:
                errors.append(f"{prefix} case is outside the fixed evaluation plan: {case_id!r}")
            else:
                for field in ("case_contract_hash", "fixture_hash", "start_state_hash"):
                    if record.get(field) != selected_case.get(field):
                        errors.append(f"{prefix} {field} differs from the evaluation plan")
            treatment = (
                plan_treatments.get(condition, {})
                if isinstance(condition, str)
                else {}
            )
            expected_treatment_hash = treatment.get("configured_manifest_hash")
            if record.get("treatment_manifest_hash") != expected_treatment_hash:
                errors.append(f"{prefix} treatment_manifest_hash differs from the evaluation plan")
            for field in ("model", "model_version", "permission_mode", "toolset_hash", "settings_hash", "grader"):
                if record.get(field) != plan_controls.get(field):
                    errors.append(f"{prefix} controlled field {field} differs from the evaluation plan")
            validate_loaded_instructions(
                record, treatment, plan_treatments, prefix, errors
            )
            validate_provenance(
                record,
                plan_controls,
                records_path.parent,
                expected_treatment_hash,
                dry_run,
                prefix,
                errors,
            )

        if isinstance(case_id, str) and condition in active_conditions and isinstance(repeat, int):
            key = (case_id, condition, repeat)
            if key in run_keys:
                errors.append(f"{prefix} duplicates case/condition/repeat: {key}")
            run_keys.add(key)
            group_records[(case_id, repeat)][condition] = record
            if valid_order:
                group = (case_id, repeat)
                order_tuple = tuple(order)
                prior = group_orders.setdefault(group, order_tuple)
                if prior != order_tuple:
                    errors.append(f"{prefix} condition_order disagrees within {group}")
                orders_by_case[case_id].add(order_tuple)
                if isinstance(position, int):
                    if position in group_positions[group]:
                        errors.append(f"{prefix} duplicates condition_position within {group}")
                    group_positions[group].add(position)

    if plan is not None:
        expected_keys = set(planned_schedule)
        missing_keys = sorted(expected_keys - run_keys)
        extra_keys = sorted(run_keys - expected_keys)
        if missing_keys:
            errors.append(f"planned matrix missing {len(missing_keys)} run record(s)")
        if extra_keys:
            errors.append(f"planned matrix contains {len(extra_keys)} unplanned run record(s)")
        for key in sorted(run_keys & expected_keys):
            case_id, condition, repeat = key
            record = group_records[(case_id, repeat)].get(condition, {})
            expected_position = planned_schedule[key]
            expected_order = tuple(
                planned_orders[(case_id, repeat)][position]
                for position in range(1, len(active_conditions) + 1)
            )
            if record.get("condition_position") != expected_position:
                errors.append(f"planned matrix cell {key} changes condition_position")
            if tuple(record.get("condition_order", [])) != expected_order:
                errors.append(f"planned matrix cell {key} changes condition_order")
    elif require_complete_matrix:
        invariant_fields = (
            "model", "model_version", "permission_mode", "toolset_hash",
            "settings_hash", "fixture_hash", "start_state_hash",
            "case_contract_hash", "oracle_hash",
        )
        complete_counts: Counter[str] = Counter()
        for group, condition_records in sorted(group_records.items()):
            present = set(condition_records)
            if present != set(LEGACY_CONDITIONS):
                errors.append(
                    f"incomplete comparison triplet {group}: has {', '.join(sorted(present))}"
                )
                continue
            complete_counts[group[0]] += 1
            for field in invariant_fields:
                values = [condition_records[condition].get(field) for condition in LEGACY_CONDITIONS]
                if any(value != values[0] for value in values[1:]):
                    errors.append(f"comparison triplet {group} changes controlled field {field}")
            position_values = [
                condition_records[condition].get("condition_position")
                for condition in LEGACY_CONDITIONS
            ]
            if not all(
                isinstance(value, int) and not isinstance(value, bool)
                for value in position_values
            ) or set(position_values) != {1, 2, 3}:
                errors.append(f"comparison triplet {group} does not occupy positions 1,2,3")
            treatment_values = [
                condition_records[condition].get("condition_artifact_hash")
                for condition in LEGACY_CONDITIONS
            ]
            if not all(isinstance(value, str) and value for value in treatment_values) or len(set(treatment_values)) != 3:
                errors.append(f"comparison triplet {group} does not identify three treatments")
        for case_id in sorted(cases):
            if complete_counts[case_id] < min_repeats:
                errors.append(
                    f"complete-triplet shortfall {case_id}: {complete_counts[case_id]} < {min_repeats}"
                )
        global_controls = (
            "model", "model_version", "permission_mode", "toolset_hash",
            "settings_hash", "oracle_hash",
        )
        all_records = [
            record
            for condition_records in group_records.values()
            for record in condition_records.values()
        ]
        if all_records:
            baseline = all_records[0]
            for field in global_controls:
                if any(record.get(field) != baseline.get(field) for record in all_records[1:]):
                    errors.append(f"comparison matrix changes global controlled field {field}")
        for case_id in sorted(cases):
            case_records = [
                record
                for (group_case, _), condition_records in group_records.items()
                if group_case == case_id
                for record in condition_records.values()
            ]
            if not case_records:
                continue
            case_baseline = case_records[0]
            for field in ("case_contract_hash", "fixture_hash", "start_state_hash"):
                if any(record.get(field) != case_baseline.get(field) for record in case_records[1:]):
                    errors.append(f"comparison matrix changes {case_id} controlled field {field}")
            for condition in LEGACY_CONDITIONS:
                treatment_values = [
                    condition_records[condition].get("condition_artifact_hash")
                    for (group_case, _), condition_records in group_records.items()
                    if group_case == case_id and condition in condition_records
                ]
                if treatment_values and any(
                    value != treatment_values[0] for value in treatment_values[1:]
                ):
                    errors.append(
                        f"comparison matrix changes {case_id}/{condition} treatment across repeats"
                    )

    if plan is None:
        for case_id, orders in sorted(orders_by_case.items()):
            repeats_for_case = {
                repeat for (group_case, repeat) in group_orders if group_case == case_id
            }
            if len(repeats_for_case) > 1 and len(orders) == 1:
                warnings.append(
                    f"{case_id} repeats all use one condition order; order effects are not counterbalanced"
                )
    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("records", type=Path, nargs="?")
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path(__file__).resolve().parent / "behavior-fixtures" / "cases.jsonl",
    )
    parser.add_argument("--require-complete-matrix", action="store_true")
    parser.add_argument("--min-repeats", type=int, default=1)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--oracle",
        type=Path,
        default=Path(__file__).resolve().parent / "09-행동-회귀-테스트.md",
    )
    args = parser.parse_args()

    cases_path = args.cases.expanduser().resolve(strict=False)
    oracle_path = args.oracle.expanduser().resolve(strict=False)
    plan_path = args.plan.expanduser().resolve(strict=False) if args.plan else None
    if args.records is None:
        if plan_path is None:
            parser.error("records is required unless --plan is supplied for plan-only validation")
        if args.dry_run:
            parser.error("--dry-run requires records")
        _, errors, warnings = validate_evaluation_plan(
            cases_path, plan_path, oracle_path=oracle_path
        )
        for warning in warnings:
            print(f"WARN: {warning}")
        for error in errors:
            print(f"FAIL: {error}")
        if errors:
            print(f"RESULT: FAIL ({len(errors)} evaluation-plan issue(s))")
            return 1
        print(
            f"RESULT: PASS ({len(warnings)} warning(s); evaluation plan only, 0 behavior executions)"
        )
        return 0

    errors, warnings = validate_behavior_records(
        cases_path,
        args.records.expanduser().resolve(strict=False),
        require_complete_matrix=args.require_complete_matrix,
        min_repeats=args.min_repeats,
        oracle_path=oracle_path,
        plan_path=plan_path,
        dry_run=args.dry_run,
    )
    for warning in warnings:
        print(f"WARN: {warning}")
    for error in errors:
        print(f"FAIL: {error}")
    if errors:
        print(f"RESULT: FAIL ({len(errors)} record-contract issue(s))")
        return 1
    if args.dry_run:
        print("RESULT: DRY-RUN STRUCTURE PASS (0 behavior executions)")
        return 0
    print(f"RESULT: PASS ({len(warnings)} warning(s); record structure only, oracle not graded)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
