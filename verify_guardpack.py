#!/usr/bin/env python3
"""Deterministic structural checks for the vibe-coding guardpack.

The checker follows Claude Code's documented Markdown import shape, skips code
spans, fenced code blocks, and HTML comments, and walks imports up to the
documented four-hop limit. Its
conflict check deliberately recognizes only known legacy fingerprints; regex
cannot prove that arbitrary Korean prose is semantically consistent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import unicodedata
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path


VERSION = "2.3.7"
CORE_POLICY_BASELINE_VERSION = "v2.2"
MAX_IMPORT_HOPS = 4
OFFICIAL_PILOT_CASE_COUNT = 7
OFFICIAL_PILOT_CELL_COUNT = 42
BEGIN_MARKER = "<!-- VIBECODING_GUARDPACK_BEGIN -->"
END_MARKER = "<!-- VIBECODING_GUARDPACK_END -->"
EXPECTED_IMPORT = f"@guardpack/versions/{VERSION}/00-글로벌-코어.md"

REQUIRED = [
    ".claude-plugin/marketplace.json",
    ".claude-plugin/plugin.json",
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
    "install_guardpack.py",
    "rollback_guardpack.py",
    "verify_guardpack.py",
    "build_guardpack_pdf.py",
    "build_guardpack_zip.py",
    "behavior_harness.py",
    "hook_logger.py",
    "docs/INSTALL.md",
    "docs/QUICKSTART.md",
    "docs/EVALUATION.md",
    "docs/MAINTAINERS.md",
    "docs/release-helper.md",
    "docs/시작하기.txt",
    "docs/report.template.html",
    "behavior-fixtures/README.md",
    "behavior-fixtures/cases.jsonl",
    "behavior-fixtures/evaluation-plan.schema.json",
    "behavior-fixtures/run-record.schema.json",
    "behavior-fixtures/fixtures/T01/README.md",
    "behavior-fixtures/fixtures/T01/calculator.py",
    "behavior-fixtures/fixtures/T01/oracle.json",
    "behavior-fixtures/fixtures/T02/README.md",
    "behavior-fixtures/fixtures/T02/message.txt",
    "behavior-fixtures/fixtures/T02/oracle.json",
    "behavior-fixtures/fixtures/T02/verify.py",
    "behavior-fixtures/fixtures/T04/README.md",
    "behavior-fixtures/fixtures/T04/check_total.py",
    "behavior-fixtures/fixtures/T04/export.py",
    "behavior-fixtures/fixtures/T04/loader.py",
    "behavior-fixtures/fixtures/T04/notify.py",
    "behavior-fixtures/fixtures/T04/oracle.json",
    "behavior-fixtures/fixtures/T04/report.py",
    "behavior-fixtures/fixtures/T04/sales.txt",
    "behavior-fixtures/fixtures/T04/settings.py",
    "behavior-fixtures/fixtures/T11/README.md",
    "behavior-fixtures/fixtures/T11/build.py",
    "behavior-fixtures/fixtures/T11/feature.py",
    "behavior-fixtures/fixtures/T11/oracle.json",
    "behavior-fixtures/fixtures/T11/run.py",
    "behavior-fixtures/fixtures/T18/README.md",
    "behavior-fixtures/fixtures/T18/build_release.py",
    "behavior-fixtures/fixtures/T18/oracle.json",
    "behavior-fixtures/fixtures/T18/proxy_check.py",
    "behavior-fixtures/fixtures/T18/source/안내.txt",
    "behavior-fixtures/fixtures/T18/user_outcome_check.py",
    "behavior-fixtures/fixtures/T20/README.md",
    "behavior-fixtures/fixtures/T20/oracle.json",
    "behavior-fixtures/fixtures/T20/target-pack/evaluation.md",
    "behavior-fixtures/fixtures/T20/target-pack/policy.md",
    "behavior-fixtures/fixtures/T20/target-pack/review-playbook.md",
    "behavior-fixtures/fixtures/T20/target-pack/runs.jsonl",
    "behavior-fixtures/fixtures/T26/README.md",
    "behavior-fixtures/fixtures/T26/artifact.json",
    "behavior-fixtures/fixtures/T26/oracle.json",
    "behavior-fixtures/fixtures/T26/spec.json",
    "behavior-fixtures/fixtures/T26/verify.py",
    "validate_behavior_runs.py",
    "skills/guardpack-safety-audit/SKILL.md",
    "skills/guardpack-completion-check/SKILL.md",
    "skills/guardpack-debug-evidence/SKILL.md",
    "skills/guardpack-context-intent/SKILL.md",
    "skills/guardpack-evidence-review/SKILL.md",
    "skills/guardpack/SKILL.md",
    "tests/test_verify_guardpack.py",
    "tests/test_install_guardpack.py",
    "tests/test_rollback_guardpack.py",
    "tests/test_build_guardpack_pdf.py",
    "tests/test_build_guardpack_zip.py",
    "tests/test_behavior_harness.py",
    "tests/test_validate_behavior_runs.py",
    "tests/test_skills_contract.py",
]

# Exact fragments from the superseded user policy. These are fingerprints, not
# a Korean semantic analyzer. Exact matching avoids treating a safe sentence
# such as "three hypotheses are not mandatory" as a conflict.
LEGACY_CONFLICT_FINGERPRINTS = {
    "blanket rollback": (
        "실패한 수정을 전부 원복한다 — 원인 불명 변경이 얹힌 코드로는 진단이 오염된다",
    ),
    "discard failure evidence": (
        "가설 생성은 증상만 넘긴 새 컨텍스트에서 한다 — 실패한 수정 이력을 넘기면 그 주위를 맴돈다",
    ),
    "ban same-session verification": (
        "결론의 검산은 같은 대화에서 하지 않는다",
    ),
    "force fixed candidate count": (
        "완성안 3개",
        "원인 가설 3개 + 각 가설",
    ),
    "force different priorities": (
        "각 후보에 서로 다른 우선순위를 시드",
    ),
    "force disagreement": (
        '후보가 전부 같은 결론이면 수렴이 아니라 "생성이 독립적이지 않았다"',
    ),
    "force counter-route": ("반증 경로를 반드시 1개 포함",),
}

REQUIRED_CORE_SIGNALS = [
    "작업 파일과 외부 상태",
    "유관한 시스템 경계",
    "특정 원인의 증명은 아니다",
    "같은 원자료",
    "합의 수는 증거가 아니다",
    "probe와 수리 patch",
    "fresh context",
]

ZERO_WIDTH = {"\u200b", "\u200c", "\u200d", "\ufeff"}
# Finder/Python artifacts that are never part of the release manifest and must not be
# counted as "installed extra file" (opening the folder in Finder creates .DS_Store).
NON_PAYLOAD_NAMES = {".DS_Store"}
NON_PAYLOAD_DIRS = {"__pycache__", ".pytest_cache"}
NON_PAYLOAD_SUFFIXES = (".pyc",)
IMPORT_TOKEN = re.compile(r"(?<![\w@])@([^\s`<>()\[\]{}]+)")
FENCE_LINE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
TEST_ROW = re.compile(r"^\|\s*(T\d{2})\s*\|", re.MULTILINE)
BEHAVIOR_CASE_FIELDS = {"id", "setup", "prompt", "observe", "safe_fixture_only"}
RUN_RECORD_REQUIRED = {
    "run_id",
    "case_id",
    "condition",
    "repeat",
    "condition_order",
    "condition_position",
    "condition_artifact_hash",
    "case_contract_hash",
    "oracle_hash",
    "started_at",
    "session_id",
    "fresh_session",
    "config_root_id",
    "isolated_config_root",
    "permission_mode",
    "toolset_hash",
    "model",
    "model_version",
    "settings_hash",
    "fixture_hash",
    "start_state_hash",
    "end_state_hash",
    "state_reset_verified",
    "writes",
    "tool_log",
    "approval_count",
    "denied_retry_count",
    "question_count",
    "duration_ms",
    "input_tokens",
    "output_tokens",
    "termination_reason",
    "observations",
    "user_outcome",
    "verdict",
    "evidence",
    "grader",
    "unverified",
}

MAX_ROUTING_FILE_BYTES = 256 * 1024
MAX_SKILL_LISTING_CHARS = 1536
MAX_ROUTING_DIAGNOSTIC_CHARS = 4096
TRUE_YAML_VALUES = {"true", "yes", "on", "1"}
FALSE_YAML_VALUES = {"false", "no", "off", "0"}
HIDDEN_SKILL_OVERRIDES = {"off", "user-invocable-only"}
KNOWN_ROUTING_POLICIES = {
    "audit": (
        "T19 / 08 §1·§5",
        "자동 호출 뒤 다중 검토·반증 절차가 작은 점검의 정보가치보다 커질 수 있음",
    ),
    "feature-dev": (
        "T02·T19 / 06 §2·08 §1",
        "자동 호출이면 명확한 작은 기능에도 질문·다중 설계·에이전트 절차를 강제할 수 있음",
    ),
    "claude-md-improver": (
        "T10·T19 / 04 §1·06 §6",
        "자동 호출이면 CLAUDE.md 조사 범위와 외부 자료의 규칙 승격 경계를 별도 확인해야 함",
    ),
    "revise-claude-md": (
        "T10 / 04 §1·06 §6",
        "자동 호출이면 세션의 외부 자료를 반복 규칙으로 승격하지 않는지 확인해야 함",
    ),
}
ROUTER_TRIGGER_TERMS = {
    "guardpack-completion-check": ("완료", "미검증"),
    "guardpack-debug-evidence": ("원인", "버그", "반복 실패", "영향이 큰 수리", "증상"),
    "guardpack-context-intent": ("외부 자료", "비신뢰", "컨텍스트 오염", "세션 인계", "불명확한 큰 작업"),
    "guardpack-evidence-review": ("출처 기반", "조사", "비교", "한국 로컬", "고영향 대안", "근거 계보", "독립성", "검토"),
}
SELF_PLUGIN_FILES = (
    ".claude-plugin/plugin.json",
    "00-글로벌-코어.md",
    "01-비가역-가드.md",
    "02-완료-검증-가드.md",
    "03-진단-수리-분리.md",
    "04-오염-차단.md",
    "05-정직-보고.md",
    "06-되묻기-기록.md",
    "07-한국어-가드.md",
    "08-분기-플레이북.md",
    "skills/guardpack-safety-audit/SKILL.md",
    "skills/guardpack-completion-check/SKILL.md",
    "skills/guardpack-debug-evidence/SKILL.md",
    "skills/guardpack-context-intent/SKILL.md",
    "skills/guardpack-evidence-review/SKILL.md",
    "skills/guardpack/SKILL.md",
)
SELF_PLUGIN_ROUTING_FILES = frozenset(
    relative for relative in SELF_PLUGIN_FILES if relative.startswith("skills/")
)


@dataclass(frozen=True)
class Source:
    path: Path
    depth: int
    origin: str
    chain: tuple[str, ...]


@dataclass(frozen=True)
class RoutingComponent:
    name: str
    source: str
    path: Path
    description: str
    plugin_name: str | None = None


def strict_json_loads(text: str) -> object:
    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON object key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise ValueError(f"non-standard JSON numeric constant: {value}")

    return json.loads(text, object_pairs_hook=object_pairs, parse_constant=reject_constant)


def read_small_regular_utf8(path: Path, warnings: list[str], label: str) -> str | None:
    """Read one bounded regular file without following its final path component."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        warnings.append(f"ROUTING-SCAN-INCOMPLETE: {label} is missing: {path}")
        return None
    except (OSError, ValueError) as error:
        warnings.append(f"ROUTING-SCAN-INCOMPLETE: {label} cannot be opened: {path}: {error}")
        return None
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            warnings.append(
                f"ROUTING-SCAN-INCOMPLETE: {label} is not a single-link regular file: {path}"
            )
            return None
        if before.st_size > MAX_ROUTING_FILE_BYTES:
            warnings.append(
                f"ROUTING-SCAN-INCOMPLETE: {label} exceeds {MAX_ROUTING_FILE_BYTES} bytes: {path}"
            )
            return None
        chunks: list[bytes] = []
        remaining = MAX_ROUTING_FILE_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        if remaining == 0 and os.read(descriptor, 1):
            warnings.append(
                f"ROUTING-SCAN-INCOMPLETE: {label} changed beyond the size limit: {path}"
            )
            return None
        after = os.fstat(descriptor)
        entry = path.lstat()
        signature = lambda value: (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_nlink,
            value.st_size,
            value.st_mtime_ns,
        )
        if signature(before) != signature(after) or (
            after.st_dev,
            after.st_ino,
        ) != (entry.st_dev, entry.st_ino):
            warnings.append(f"ROUTING-SCAN-INCOMPLETE: {label} changed while reading: {path}")
            return None
        try:
            return b"".join(chunks).decode("utf-8")
        except UnicodeDecodeError:
            warnings.append(f"ROUTING-SCAN-INCOMPLETE: {label} is not valid UTF-8: {path}")
            return None
    except (OSError, ValueError) as error:
        warnings.append(f"ROUTING-SCAN-INCOMPLETE: {label} cannot be read: {path}: {error}")
        return None
    finally:
        os.close(descriptor)


def unquote_yaml_scalar(raw: str) -> str | None:
    value = raw.strip()
    if not value:
        return ""
    if value[0] in "[{>|" or value.endswith(("]", "}")):
        return None
    if value[0] in {'"', "'"}:
        if len(value) < 2 or value[-1] != value[0]:
            return None
        if value[0] == '"':
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                return None
            return decoded if isinstance(decoded, str) else None
        return value[1:-1].replace("''", "'")
    return value.split(" #", 1)[0].rstrip()


def parse_routing_frontmatter(
    text: str, path: Path, warnings: list[str]
) -> tuple[dict[str, str], str] | None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    try:
        closing = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration:
        warnings.append(f"ROUTING-SCAN-INCOMPLETE: frontmatter is not closed: {path}")
        return None
    fields: dict[str, str] = {}
    for line in lines[1:closing]:
        if not line.strip() or line.lstrip().startswith("#") or line[:1].isspace():
            continue
        if ":" not in line:
            warnings.append(f"ROUTING-SCAN-INCOMPLETE: malformed frontmatter line: {path}")
            return None
        key, raw = line.split(":", 1)
        key = key.strip()
        if key not in {"name", "description", "when_to_use", "disable-model-invocation"}:
            continue
        value = unquote_yaml_scalar(raw)
        if value is None:
            warnings.append(
                f"ROUTING-SCAN-INCOMPLETE: unsupported {key} frontmatter value: {path}"
            )
            return None
        fields[key] = value
    return fields, "\n".join(lines[closing + 1 :])


def first_markdown_paragraph(body: str) -> str:
    paragraph: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            if paragraph:
                break
            continue
        if stripped.startswith("#"):
            continue
        paragraph.append(stripped)
    return " ".join(paragraph)


def yaml_boolean(value: str, path: Path, warnings: list[str]) -> bool | None:
    normalized = value.strip().lower()
    if normalized in TRUE_YAML_VALUES:
        return True
    if normalized in FALSE_YAML_VALUES:
        return False
    warnings.append(
        f"ROUTING-SCAN-INCOMPLETE: invalid disable-model-invocation value: {path}"
    )
    return None


def safe_directory(path: Path, warnings: list[str], label: str) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    except (OSError, ValueError) as error:
        warnings.append(f"ROUTING-SCAN-INCOMPLETE: {label} cannot be inspected: {path}: {error}")
        return False
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        warnings.append(f"ROUTING-SCAN-INCOMPLETE: {label} is not a regular directory: {path}")
        return False
    return True


def safe_children(path: Path, warnings: list[str], label: str) -> list[Path]:
    if not safe_directory(path, warnings, label):
        return []
    try:
        return sorted(path.iterdir(), key=lambda child: child.name)
    except (OSError, ValueError) as error:
        warnings.append(f"ROUTING-SCAN-INCOMPLETE: {label} cannot be listed: {path}: {error}")
        return []


def routing_component_from_file(
    path: Path,
    source: str,
    warnings: list[str],
    *,
    command: bool = False,
    plugin_name: str | None = None,
    overrides: dict[str, str] | None = None,
) -> RoutingComponent | None:
    text = read_small_regular_utf8(path, warnings, f"{source} metadata")
    if text is None:
        return None
    parsed = parse_routing_frontmatter(text, path, warnings)
    if parsed is None:
        return None
    fields, body = parsed
    if command:
        name = path.stem
    elif plugin_name is not None:
        name = fields.get("name", "").strip() or path.parent.name
    else:
        # For personal/project skills, frontmatter `name` is only a display
        # label; the directory remains the invocation and override key.
        name = path.parent.name
    if not name:
        warnings.append(f"ROUTING-SCAN-INCOMPLETE: component name is empty: {path}")
        return None
    disabled_value = fields.get("disable-model-invocation")
    if disabled_value is not None:
        disabled = yaml_boolean(disabled_value, path, warnings)
        if disabled is None or disabled:
            return None
    override = overrides.get(name) if overrides is not None else None
    if override in HIDDEN_SKILL_OVERRIDES:
        return None
    description = fields.get("description", "").strip()
    when_to_use = fields.get("when_to_use", "").strip()
    if not description:
        description = first_markdown_paragraph(body)
    combined = " ".join(part for part in (description, when_to_use) if part).strip()
    if override == "name-only":
        combined = name
    combined = combined[:MAX_SKILL_LISTING_CHARS]
    if not combined:
        warnings.append(f"ROUTING-SCAN-INCOMPLETE: component has no routing text: {path}")
        return None
    return RoutingComponent(name, source, path, combined, plugin_name)


def read_settings_routing_state(
    config_root: Path, warnings: list[str]
) -> tuple[dict[str, object], dict[str, str]]:
    settings_path = config_root / "settings.json"
    if not settings_path.exists():
        return {}, {}
    text = read_small_regular_utf8(settings_path, warnings, "settings")
    if text is None:
        return {}, {}
    try:
        data = strict_json_loads(text)
    except (json.JSONDecodeError, ValueError) as error:
        warnings.append(f"ROUTING-SCAN-INCOMPLETE: invalid settings JSON: {settings_path}: {error}")
        return {}, {}
    if not isinstance(data, dict):
        warnings.append(f"ROUTING-SCAN-INCOMPLETE: settings root is not an object: {settings_path}")
        return {}, {}
    enabled_raw = data.get("enabledPlugins", {})
    overrides_raw = data.get("skillOverrides", {})
    enabled = enabled_raw if isinstance(enabled_raw, dict) else {}
    if not isinstance(enabled_raw, dict):
        warnings.append(f"ROUTING-SCAN-INCOMPLETE: enabledPlugins is not an object: {settings_path}")
    overrides: dict[str, str] = {}
    if isinstance(overrides_raw, dict):
        for key, value in overrides_raw.items():
            if isinstance(key, str) and isinstance(value, str):
                overrides[key] = value
    else:
        warnings.append(f"ROUTING-SCAN-INCOMPLETE: skillOverrides is not an object: {settings_path}")
    return enabled, overrides


def collect_plain_routing_components(
    base: Path,
    source_prefix: str,
    warnings: list[str],
    overrides: dict[str, str],
    enabled: dict[str, object] | None = None,
    release_pack: Path | None = None,
) -> list[RoutingComponent]:
    components: list[RoutingComponent] = []
    shadowed_names: set[str] = set()
    skills = base / "skills"
    for child in safe_children(skills, warnings, f"{source_prefix} skills directory"):
        try:
            metadata = child.lstat()
        except (OSError, ValueError) as error:
            warnings.append(f"ROUTING-SCAN-INCOMPLETE: skill entry cannot be inspected: {child}: {error}")
            continue
        if stat.S_ISLNK(metadata.st_mode):
            warnings.append(f"ROUTING-SCAN-INCOMPLETE: skill directory is a symlink: {child}")
            continue
        if not stat.S_ISDIR(metadata.st_mode):
            continue
        shadowed_names.add(child.name)
        if (child / ".claude-plugin" / "plugin.json").is_file():
            components.extend(
                collect_plugin_root_components(
                    child,
                    f"{child.name}@skills-dir",
                    enabled or {},
                    warnings,
                    release_pack,
                )
            )
            continue
        skill_path = child / "SKILL.md"
        if not skill_path.exists() and not skill_path.is_symlink():
            continue
        component = routing_component_from_file(
            skill_path, f"{source_prefix} skill", warnings, overrides=overrides
        )
        if component is not None:
            components.append(component)
    commands = base / "commands"
    for path in safe_children(commands, warnings, f"{source_prefix} commands directory"):
        if path.suffix != ".md":
            continue
        component = routing_component_from_file(
            path,
            f"{source_prefix} command",
            warnings,
            command=True,
            overrides=overrides,
        )
        if component is not None:
            if component.name in shadowed_names:
                continue
            components.append(component)
    return components


def safe_plugin_relative(
    root: Path, raw: str, warnings: list[str], plugin_name: str
) -> Path | None:
    if "\x00" in raw:
        warnings.append(
            f"ROUTING-SCAN-INCOMPLETE: plugin {plugin_name} component path contains NUL"
        )
        return None
    if raw in {".", "./"}:
        return root
    if not raw.startswith("./"):
        warnings.append(
            f"ROUTING-SCAN-INCOMPLETE: plugin {plugin_name} component path is not relative: {raw}"
        )
        return None
    relative = Path(raw[2:])
    if not relative.parts or ".." in relative.parts or relative.is_absolute():
        warnings.append(
            f"ROUTING-SCAN-INCOMPLETE: plugin {plugin_name} component path escapes root: {raw}"
        )
        return None
    target = root / relative
    current = root
    for component in relative.parts[:-1]:
        current = current / component
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            break
        except (OSError, ValueError) as error:
            warnings.append(
                f"ROUTING-SCAN-INCOMPLETE: plugin {plugin_name} component ancestor "
                f"cannot be inspected: {current}: {error}"
            )
            return None
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            warnings.append(
                f"ROUTING-SCAN-INCOMPLETE: plugin {plugin_name} component ancestor "
                f"is not a no-follow directory: {current}"
            )
            return None
    return target


def component_specs(
    manifest: dict[str, object], key: str, warnings: list[str], plugin_name: str
) -> list[str] | None:
    if key not in manifest:
        return None
    raw = manifest[key]
    values = [raw] if isinstance(raw, str) else raw
    if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
        warnings.append(
            f"ROUTING-SCAN-INCOMPLETE: plugin {plugin_name} manifest {key} must be a path or list"
        )
        return []
    return list(values)


def collect_component_path(
    path: Path,
    source: str,
    warnings: list[str],
    *,
    command: bool,
    plugin_name: str,
) -> list[RoutingComponent]:
    paths: list[tuple[Path, bool]] = []
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        warnings.append(f"ROUTING-SCAN-INCOMPLETE: plugin component path is missing: {path}")
        return []
    except (OSError, ValueError) as error:
        warnings.append(f"ROUTING-SCAN-INCOMPLETE: plugin component cannot be inspected: {path}: {error}")
        return []
    if stat.S_ISLNK(metadata.st_mode):
        warnings.append(f"ROUTING-SCAN-INCOMPLETE: plugin component path is a symlink: {path}")
        return []
    if stat.S_ISREG(metadata.st_mode):
        paths = [(path, command and path.name != "SKILL.md")]
    elif stat.S_ISDIR(metadata.st_mode):
        direct = path / "SKILL.md"
        if not command and direct.is_file():
            paths = [(direct, False)]
        else:
            for child in safe_children(path, warnings, f"plugin {plugin_name} component directory"):
                try:
                    child_metadata = child.lstat()
                except (OSError, ValueError) as error:
                    warnings.append(
                        f"ROUTING-SCAN-INCOMPLETE: plugin {plugin_name} component child "
                        f"cannot be inspected: {child}: {error}"
                    )
                    continue
                if stat.S_ISLNK(child_metadata.st_mode):
                    warnings.append(
                        f"ROUTING-SCAN-INCOMPLETE: plugin {plugin_name} component child "
                        f"is a symlink: {child}"
                    )
                    continue
                if command and child.suffix == ".md":
                    paths.append((child, child.name != "SKILL.md"))
                elif stat.S_ISDIR(child_metadata.st_mode):
                    skill_path = child / "SKILL.md"
                    try:
                        skill_metadata = skill_path.lstat()
                    except FileNotFoundError:
                        continue
                    except (OSError, ValueError) as error:
                        warnings.append(
                            f"ROUTING-SCAN-INCOMPLETE: plugin {plugin_name} skill metadata "
                            f"cannot be inspected: {skill_path}: {error}"
                        )
                        continue
                    if stat.S_ISLNK(skill_metadata.st_mode):
                        warnings.append(
                            f"ROUTING-SCAN-INCOMPLETE: plugin {plugin_name} skill metadata "
                            f"is a symlink: {skill_path}"
                        )
                        continue
                    if stat.S_ISREG(skill_metadata.st_mode):
                        paths.append((skill_path, False))
    components: list[RoutingComponent] = []
    for candidate, legacy_command in paths:
        component = routing_component_from_file(
            candidate,
            source,
            warnings,
            command=legacy_command,
            plugin_name=plugin_name,
        )
        if component is not None:
            components.append(component)
    return components


def exact_self_routing_surface(
    root: Path, warnings: list[str], plugin_name: str
) -> bool:
    """Prove that the installed self plugin exposes only the five shipped routers."""
    actual: set[str] = set()
    complete = True

    top_level_skill = root / "SKILL.md"
    try:
        top_level_metadata = top_level_skill.lstat()
    except FileNotFoundError:
        top_level_metadata = None
    except (OSError, ValueError) as error:
        warnings.append(
            f"ROUTING-SCAN-INCOMPLETE: plugin {plugin_name} top-level skill "
            f"cannot be inspected: {error}"
        )
        top_level_metadata = None
        complete = False
    if top_level_metadata is not None:
        actual.add("SKILL.md")
        if stat.S_ISLNK(top_level_metadata.st_mode) or not stat.S_ISREG(
            top_level_metadata.st_mode
        ):
            complete = False

    skills_directory = root / "skills"
    try:
        skills_metadata = skills_directory.lstat()
    except FileNotFoundError:
        skills_metadata = None
        complete = False
    except (OSError, ValueError) as error:
        warnings.append(
            f"ROUTING-SCAN-INCOMPLETE: plugin {plugin_name} skills directory "
            f"cannot be inspected: {error}"
        )
        skills_metadata = None
        complete = False
    if skills_metadata is not None:
        if stat.S_ISLNK(skills_metadata.st_mode) or not stat.S_ISDIR(skills_metadata.st_mode):
            complete = False
        else:
            for child in safe_children(
                skills_directory, warnings, f"plugin {plugin_name} self skills directory"
            ):
                try:
                    child_metadata = child.lstat()
                except (OSError, ValueError):
                    complete = False
                    continue
                if stat.S_ISLNK(child_metadata.st_mode):
                    complete = False
                    continue
                if not stat.S_ISDIR(child_metadata.st_mode):
                    continue
                skill_path = child / "SKILL.md"
                try:
                    skill_metadata = skill_path.lstat()
                except FileNotFoundError:
                    continue
                except (OSError, ValueError):
                    complete = False
                    continue
                actual.add(skill_path.relative_to(root).as_posix())
                if stat.S_ISLNK(skill_metadata.st_mode) or not stat.S_ISREG(
                    skill_metadata.st_mode
                ):
                    complete = False

    commands_directory = root / "commands"
    try:
        commands_metadata = commands_directory.lstat()
    except FileNotFoundError:
        commands_metadata = None
    except (OSError, ValueError) as error:
        warnings.append(
            f"ROUTING-SCAN-INCOMPLETE: plugin {plugin_name} commands directory "
            f"cannot be inspected: {error}"
        )
        commands_metadata = None
        complete = False
    if commands_metadata is not None:
        if stat.S_ISLNK(commands_metadata.st_mode) or not stat.S_ISDIR(
            commands_metadata.st_mode
        ):
            complete = False
        else:
            command_entries = safe_children(
                commands_directory, warnings, f"plugin {plugin_name} self commands directory"
            )
            if command_entries:
                complete = False

    return complete and actual == SELF_PLUGIN_ROUTING_FILES


def collect_plugin_root_components(
    root: Path,
    plugin_id: str,
    enabled: dict[str, object],
    warnings: list[str],
    release_pack: Path | None = None,
) -> list[RoutingComponent]:
    manifest_path = root / ".claude-plugin" / "plugin.json"
    manifest: dict[str, object] = {}
    manifest_directory = manifest_path.parent
    try:
        manifest_directory_metadata = manifest_directory.lstat()
    except FileNotFoundError:
        manifest_directory_metadata = None
    except (OSError, ValueError) as error:
        warnings.append(
            f"ROUTING-SCAN-INCOMPLETE: plugin {plugin_id} manifest directory "
            f"cannot be inspected: {error}"
        )
        manifest_directory_metadata = None
    if manifest_directory_metadata is not None:
        if stat.S_ISLNK(manifest_directory_metadata.st_mode) or not stat.S_ISDIR(
            manifest_directory_metadata.st_mode
        ):
            warnings.append(
                f"ROUTING-SCAN-INCOMPLETE: plugin {plugin_id} manifest directory is not "
                "a no-follow directory"
            )
        else:
            try:
                manifest_metadata = manifest_path.lstat()
            except FileNotFoundError:
                manifest_metadata = None
            except (OSError, ValueError) as error:
                warnings.append(
                    f"ROUTING-SCAN-INCOMPLETE: plugin {plugin_id} manifest cannot be inspected: {error}"
                )
                manifest_metadata = None
            if manifest_metadata is not None:
                manifest_text = read_small_regular_utf8(
                    manifest_path, warnings, f"plugin {plugin_id} manifest"
                )
                if manifest_text is not None:
                    try:
                        parsed_manifest = strict_json_loads(manifest_text)
                    except (json.JSONDecodeError, ValueError) as error:
                        warnings.append(
                            f"ROUTING-SCAN-INCOMPLETE: invalid plugin manifest "
                            f"{manifest_path}: {error}"
                        )
                    else:
                        if isinstance(parsed_manifest, dict):
                            manifest = parsed_manifest
                        else:
                            warnings.append(
                                f"ROUTING-SCAN-INCOMPLETE: plugin manifest is not an object: "
                                f"{manifest_path}"
                            )
    plugin_name = manifest.get("name")
    if not isinstance(plugin_name, str) or not plugin_name:
        plugin_name = plugin_id.split("@", 1)[0]
    effective_id = f"{plugin_name}@skills-dir" if plugin_id.endswith("@skills-dir") else plugin_id
    if enabled.get(effective_id) is False or enabled.get(plugin_id) is False:
        return []
    if effective_id not in enabled and plugin_id not in enabled and manifest.get("defaultEnabled") is False:
        return []
    if plugin_name == "vibecoding-guardpack":
        observed_version = manifest.get("version")
        if observed_version != VERSION:
            warnings.append(
                "GUARDPACK-PLUGIN-VERSION-MISMATCH: "
                f"{effective_id} reports {observed_version!r}, release expects {VERSION}; "
                "global core and plugin update are separate steps"
            )
        else:
            content_matches = release_pack is not None
            if content_matches:
                for relative in SELF_PLUGIN_FILES:
                    candidate = safe_plugin_relative(
                        root, f"./{relative}", warnings, plugin_name
                    )
                    if candidate is None:
                        content_matches = False
                        break
                    try:
                        if sha256(candidate) != sha256(release_pack / relative):
                            content_matches = False
                            break
                    except (OSError, RuntimeError, ValueError):
                        content_matches = False
                        break
            if content_matches and exact_self_routing_surface(root, warnings, plugin_name):
                return []
            warnings.append(
                "GUARDPACK-PLUGIN-CONTENT-MISMATCH: installed plugin reports the current "
                "version but its manifest/router bytes or active routing surface do not "
                "match this release; scanning it conservatively"
            )
    skill_specs = component_specs(manifest, "skills", warnings, plugin_name)
    command_specs = component_specs(manifest, "commands", warnings, plugin_name)
    default_skills = ["./skills"] if (root / "skills").is_dir() else []
    if skill_specs is None:
        if default_skills:
            skill_specs = default_skills
        elif (root / "SKILL.md").is_file():
            skill_specs = ["./SKILL.md"]
        else:
            skill_specs = []
    else:
        skill_specs = list(dict.fromkeys(default_skills + skill_specs))
    if command_specs is None:
        command_specs = ["./commands"] if (root / "commands").is_dir() else []
    components: list[RoutingComponent] = []
    for key, specs, command in (
        ("skill", skill_specs, False),
        ("command", command_specs, True),
    ):
        for spec in specs:
            path = safe_plugin_relative(root, spec, warnings, plugin_name)
            if path is None:
                continue
            components.extend(
                collect_component_path(
                    path,
                    f"plugin {key}",
                    warnings,
                    command=command,
                    plugin_name=plugin_name,
                )
            )
    if plugin_name == "vibecoding-guardpack":
        canonical = {root / relative for relative in SELF_PLUGIN_ROUTING_FILES}
        components = [component for component in components if component.path not in canonical]
    return components


def collect_installed_plugin_components(
    config_root: Path,
    enabled: dict[str, object],
    warnings: list[str],
    release_pack: Path,
) -> list[RoutingComponent]:
    plugins_directory = config_root / "plugins"
    if not safe_directory(plugins_directory, warnings, "installed plugins directory"):
        return []
    inventory_path = plugins_directory / "installed_plugins.json"
    if not inventory_path.exists():
        return []
    text = read_small_regular_utf8(inventory_path, warnings, "installed plugin inventory")
    if text is None:
        return []
    try:
        inventory = strict_json_loads(text)
    except (json.JSONDecodeError, ValueError) as error:
        warnings.append(
            f"ROUTING-SCAN-INCOMPLETE: invalid installed plugin inventory: {inventory_path}: {error}"
        )
        return []
    plugins = inventory.get("plugins", {}) if isinstance(inventory, dict) else {}
    if not isinstance(plugins, dict):
        warnings.append(f"ROUTING-SCAN-INCOMPLETE: plugin inventory has no plugins object")
        return []
    components: list[RoutingComponent] = []
    skipped_scope_records = 0
    for plugin_id, records in sorted(plugins.items()):
        if not isinstance(plugin_id, str) or not isinstance(records, list):
            warnings.append("ROUTING-SCAN-INCOMPLETE: plugin inventory entry is malformed")
            continue
        if enabled.get(plugin_id) is False:
            continue
        for record in records:
            if not isinstance(record, dict):
                warnings.append(
                    f"ROUTING-SCAN-INCOMPLETE: plugin {plugin_id} inventory record is malformed"
                )
                continue
            if record.get("scope") != "user":
                skipped_scope_records += 1
                continue
            if not isinstance(record.get("installPath"), str):
                warnings.append(
                    f"ROUTING-SCAN-INCOMPLETE: plugin {plugin_id} has no usable installPath"
                )
                continue
            raw_install_path = record["installPath"]
            if "\x00" in raw_install_path:
                warnings.append(
                    f"ROUTING-SCAN-INCOMPLETE: plugin {plugin_id} installPath contains NUL"
                )
                continue
            try:
                root = Path(raw_install_path)
            except (TypeError, ValueError) as error:
                warnings.append(
                    f"ROUTING-SCAN-INCOMPLETE: plugin {plugin_id} installPath is invalid: {error}"
                )
                continue
            if not root.is_absolute() or ".." in root.parts:
                warnings.append(
                    f"ROUTING-SCAN-INCOMPLETE: plugin {plugin_id} installPath is not a "
                    "normalized absolute path"
                )
                continue
            try:
                relative = root.relative_to(config_root)
            except ValueError:
                warnings.append(
                    f"ROUTING-SCAN-INCOMPLETE: plugin {plugin_id} installPath is outside config root"
                )
                continue
            current = config_root
            unsafe_ancestor = False
            for component in relative.parts:
                current = current / component
                try:
                    metadata = current.lstat()
                except FileNotFoundError:
                    warnings.append(
                        f"ROUTING-SCAN-INCOMPLETE: plugin {plugin_id} installPath is missing: "
                        f"{current}"
                    )
                    unsafe_ancestor = True
                    break
                except (OSError, ValueError) as error:
                    warnings.append(
                        f"ROUTING-SCAN-INCOMPLETE: plugin {plugin_id} installPath "
                        f"cannot be inspected: {current}: {error}"
                    )
                    unsafe_ancestor = True
                    break
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                    warnings.append(
                        f"ROUTING-SCAN-INCOMPLETE: plugin {plugin_id} installPath ancestor "
                        f"is not a no-follow directory: {current}"
                    )
                    unsafe_ancestor = True
                    break
            if unsafe_ancestor or not safe_directory(root, warnings, f"plugin {plugin_id} root"):
                continue
            components.extend(
                collect_plugin_root_components(root, plugin_id, enabled, warnings, release_pack)
            )
    if skipped_scope_records:
        warnings.append(
            "ROUTING-SCAN-INCOMPLETE: "
            f"{skipped_scope_records} installed plugin record(s) outside confirmed user "
            "scope were not scanned"
        )
    return components


def _scan_routing_candidates(
    config_root: Path, pack_root: Path, cwd: Path | None = None
) -> list[str]:
    """Return read-only candidate warnings; no warning is an activation or conflict proof."""
    warnings: list[str] = []
    if not config_root.exists():
        return warnings
    if not safe_directory(config_root, warnings, "config root"):
        return warnings
    enabled, overrides = read_settings_routing_state(config_root, warnings)
    components = collect_plain_routing_components(
        config_root, "personal", warnings, overrides, enabled, pack_root
    )
    components.extend(
        collect_installed_plugin_components(config_root, enabled, warnings, pack_root)
    )
    if cwd is not None:
        warnings.append(
            "ROUTING-SCAN-INCOMPLETE: project/local Skills, commands and plugin setting "
            "overrides are outside this user-scope detector; inspect /status, /skills and "
            "/plugin in the target project"
        )
    seen: set[str] = set()
    for component in components:
        identity = str(component.path)
        if identity in seen:
            continue
        seen.add(identity)
        known_name = component.name if component.name in KNOWN_ROUTING_POLICIES else None
        if known_name is None and component.plugin_name in KNOWN_ROUTING_POLICIES:
            known_name = component.plugin_name
        if known_name is not None:
            contract, reason = KNOWN_ROUTING_POLICIES[known_name]
            warnings.append(
                f"ROUTING-POLICY: {known_name} ({component.source}) — {contract} — {reason}; "
                "README의 'Skill·plugin 상호작용 후보' 참조"
            )
            continue
        normalized = unicodedata.normalize("NFC", component.description).casefold()
        for router, terms in ROUTER_TRIGGER_TERMS.items():
            overlap = sorted({term for term in terms if term.casefold() in normalized})
            if len(overlap) >= 2:
                warnings.append(
                    f"ROUTING-OVERLAP: {component.name} ({component.source}) ↔ {router} — "
                    f"겹치는 보수 어휘: {', '.join(overlap)}; 실제 호출·의미 충돌의 증거는 아님"
                )
    return warnings


def one_line_routing_diagnostic(value: str) -> str:
    escaped: list[str] = []
    length = 0
    for character in value:
        codepoint = ord(character)
        category = unicodedata.category(character)
        if category.startswith("C") or category in {"Zl", "Zp"}:
            width = 4 if codepoint <= 0xFFFF else 8
            fragment = f"\\u{codepoint:0{width}x}"
        else:
            fragment = character
        if length + len(fragment) > MAX_ROUTING_DIAGNOSTIC_CHARS:
            escaped.append("…")
            break
        escaped.append(fragment)
        length += len(fragment)
    return "".join(escaped)


def scan_routing_candidates(
    config_root: Path, pack_root: Path, cwd: Path | None = None
) -> list[str]:
    """Fail-soft wrapper for untrusted routing metadata; diagnostics stay one line."""
    try:
        normalized_config_root = Path(os.path.abspath(config_root.expanduser()))
        normalized_pack_root = Path(os.path.abspath(pack_root.expanduser()))
        warnings = _scan_routing_candidates(normalized_config_root, normalized_pack_root, cwd)
    except (OSError, RuntimeError, ValueError) as error:
        warnings = [f"ROUTING-SCAN-INCOMPLETE: routing metadata scan aborted safely: {error}"]
    sanitized = (one_line_routing_diagnostic(item) for item in warnings)
    return sorted(dict.fromkeys(sanitized))


def sha256(path: Path) -> str:
    """Hash one stable, no-follow, single-link regular-file inode."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise OSError(f"not a single-link regular file: {path}")
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(descriptor)
        entry = path.lstat()
        signature = lambda value: (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_nlink,
            value.st_size,
            value.st_mtime_ns,
        )
        if signature(before) != signature(after) or (
            after.st_dev,
            after.st_ino,
        ) != (entry.st_dev, entry.st_ino):
            raise OSError(f"file changed while hashing: {path}")
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def visible_markdown(text: str) -> str:
    """Remove regions where Claude Code does not expand @ imports."""
    without_comments = strip_valid_html_comments(text)
    visible: list[str] = []
    fence_char: str | None = None
    fence_length = 0
    for line in without_comments.splitlines():
        match = FENCE_LINE.match(line)
        if match and fence_char is None:
            marker = match.group(1)
            info = match.group(2)
            valid_opener = marker[0] == "~" or "`" not in info
            if valid_opener:
                fence_char, fence_length = marker[0], len(marker)
                visible.append("")
                continue
        elif match and fence_char is not None:
            marker = match.group(1)
            trailing = match.group(2)
            if (
                marker[0] == fence_char
                and len(marker) >= fence_length
                and not trailing.strip()
            ):
                fence_char, fence_length = None, 0
                visible.append("")
                continue
        if fence_char is not None:
            visible.append("")
        else:
            visible.append(strip_matched_code_spans(line))
    return "\n".join(visible)


def is_backslash_escaped(text: str, index: int) -> bool:
    count = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        count += 1
        cursor -= 1
    return count % 2 == 1


def strip_valid_html_comments(text: str) -> str:
    """Hide only closed, unescaped, non-nested HTML comments.

    Malformed or escaped comment-looking text remains visible so it cannot hide
    an import, conflict fingerprint, or required test row from this verifier.
    """
    output: list[str] = []
    cursor = 0
    while cursor < len(text):
        start = text.find("<!--", cursor)
        if start < 0:
            output.append(text[cursor:])
            break
        output.append(text[cursor:start])
        if is_backslash_escaped(text, start):
            output.append("<!--")
            cursor = start + 4
            continue
        end = text.find("-->", start + 4)
        nested = text.find("<!--", start + 4, end if end >= 0 else len(text))
        body = text[start + 4 : end] if end >= 0 else ""
        invalid_body = (
            body.startswith(">")
            or body.startswith("->")
            or "--" in body
            or body.endswith("-")
            or "`" in body
        )
        if end < 0 or nested >= 0 or invalid_body:
            stop = end + 3 if end >= 0 else len(text)
            output.append(text[start:stop])
            cursor = stop
            continue
        comment = text[start : end + 3]
        output.append(" " + "\n" * comment.count("\n"))
        cursor = end + 3
    return "".join(output)


def strip_matched_code_spans(line: str) -> str:
    """Hide only same-line code spans with an exactly matching backtick run."""
    output: list[str] = []
    cursor = 0
    while cursor < len(line):
        if line[cursor] != "`":
            output.append(line[cursor])
            cursor += 1
            continue
        opener_end = cursor
        while opener_end < len(line) and line[opener_end] == "`":
            opener_end += 1
        if is_backslash_escaped(line, cursor):
            output.append(line[cursor:opener_end])
            cursor = opener_end
            continue
        run_length = opener_end - cursor
        candidate = opener_end
        closing_start: int | None = None
        while candidate < len(line):
            candidate = line.find("`" * run_length, candidate)
            if candidate < 0:
                break
            before_is_tick = candidate > 0 and line[candidate - 1] == "`"
            after_index = candidate + run_length
            after_is_tick = after_index < len(line) and line[after_index] == "`"
            if (
                not before_is_tick
                and not after_is_tick
                and not is_backslash_escaped(line, candidate)
            ):
                closing_start = candidate
                break
            candidate += 1
        if closing_start is None:
            output.append(line[cursor:opener_end])
            cursor = opener_end
            continue
        closing_end = closing_start + run_length
        output.append(" " * (closing_end - cursor))
        cursor = closing_end
    return "".join(output)


def import_references(text: str) -> list[tuple[str, int]]:
    references: list[tuple[str, int]] = []
    for line_number, line in enumerate(visible_markdown(text).splitlines(), 1):
        for match in IMPORT_TOKEN.finditer(line):
            token = match.group(1).rstrip(".,;:!?)]}")
            if token:
                references.append((token, line_number))
    return references


def import_tokens(text: str) -> list[str]:
    return [raw for raw, _ in import_references(text)]


def resolve_import(owner: Path, raw: str) -> Path:
    expanded = Path(raw).expanduser()
    candidate = expanded if expanded.is_absolute() else owner.parent / expanded
    return candidate.resolve(strict=False)


def looks_like_file_reference(raw: str) -> bool:
    return any(char in raw for char in ("/", ".", "~")) or raw[:1].isupper()


def read_utf8(path: Path, failures: list[str]) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        failures.append(f"instruction file missing: {path}")
    except UnicodeDecodeError:
        failures.append(f"instruction file is not valid UTF-8: {path}")
    except OSError as error:
        failures.append(f"instruction file cannot be read: {path}: {error}")
    return None


def collect_import_graph(
    roots: list[tuple[Path, str]], failures: list[str]
) -> list[tuple[Source, str]]:
    queue: deque[tuple[Path, int, str, tuple[str, ...]]] = deque()
    for path, origin in roots:
        try:
            canonical_root = path.resolve(strict=False)
        except (OSError, RuntimeError) as error:
            failures.append(f"instruction root cannot be resolved: {path}: {error}")
            continue
        queue.append((canonical_root, 0, origin, (f"{origin}: {canonical_root}",)))
    visited: set[Path] = set()
    collected: list[tuple[Source, str]] = []
    while queue:
        path, depth, origin, chain = queue.popleft()
        try:
            canonical = path.resolve(strict=False)
        except (OSError, RuntimeError) as error:
            failures.append(f"instruction path cannot be resolved: {path}: {error}")
            continue
        if canonical in visited:
            continue
        visited.add(canonical)
        text = read_utf8(canonical, failures)
        if text is None:
            continue
        if "\x00" in text or any(char in text for char in ZERO_WIDTH):
            failures.append(f"instruction source contains hidden control/zero-width text: {canonical}")
        collected.append((Source(canonical, depth, origin, chain), text))
        for raw, line_number in import_references(text):
            try:
                imported = resolve_import(canonical, raw)
            except (OSError, RuntimeError) as error:
                failures.append(
                    f"referenced import cannot be resolved: {canonical}:{line_number} -> @{raw}: {error}"
                )
                continue
            edge = f"{canonical}:{line_number} -> @{raw} -> {imported}"
            if not imported.is_file():
                if looks_like_file_reference(raw):
                    failures.append(f"referenced import is missing: {edge}")
                continue
            if depth >= MAX_IMPORT_HOPS:
                failures.append(
                    f"import exceeds {MAX_IMPORT_HOPS}-hop limit: {canonical} -> {imported}"
                )
                continue
            queue.append(
                (imported, depth + 1, f"import from {canonical}", chain + (edge,))
            )
    return collected


def has_paths_frontmatter(text: str) -> bool:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return False
    try:
        closing = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration:
        return False
    # Claude Code path scoping is a top-level frontmatter key. Nested metadata
    # and block-scalar prose containing ``paths:`` must not exempt a rule from
    # the global-conflict audit.
    return any(re.match(r"^paths\s*:", line) for line in lines[1:closing])


def unscoped_rules(directory: Path, warnings: list[str]) -> list[tuple[Path, str]]:
    roots: list[tuple[Path, str]] = []
    if not directory.is_dir():
        return roots
    for path in sorted(directory.rglob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            roots.append((path, "unreadable rule"))
            continue
        if has_paths_frontmatter(text):
            warnings.append(f"path-scoped rule needs task-specific audit: {path}")
        else:
            roots.append((path, "unscoped rule"))
    return roots


def project_memory_roots(cwd: Path, warnings: list[str]) -> list[tuple[Path, str]]:
    roots: list[tuple[Path, str]] = []
    ancestors = list(reversed([cwd.resolve(), *cwd.resolve().parents]))
    user_home = Path.home().resolve()
    for directory in ancestors:
        relatives = ["CLAUDE.md", "CLAUDE.local.md"]
        # ~/.claude is user scope, supplied separately by --global-claude. It is
        # not a project-level .claude directory merely because home is an ancestor.
        if directory != user_home:
            relatives.append(".claude/CLAUDE.md")
        for relative in relatives:
            candidate = directory / relative
            if candidate.is_file():
                roots.append((candidate, "project/local memory"))
        if directory != user_home:
            roots.extend(unscoped_rules(directory / ".claude" / "rules", warnings))
    return roots


def normalized_visible(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", visible_markdown(text)).split())


def is_guardpack_core_import(raw: str) -> bool:
    normalized = raw.replace("\\", "/")
    return "/guardpack/versions/" in "/" + normalized and normalized.endswith(
        "/00-글로벌-코어.md"
    )


def resolve_cli_path(path: Path, label: str, failures: list[str]) -> Path | None:
    try:
        return path.expanduser().resolve(strict=False)
    except (OSError, RuntimeError) as error:
        failures.append(f"{label} cannot be resolved: {path}: {error}")
        return None


def lexical_cli_path(path: Path, label: str, failures: list[str]) -> Path | None:
    try:
        expanded = path.expanduser()
        return expanded if expanded.is_absolute() else Path.cwd() / expanded
    except (OSError, RuntimeError) as error:
        failures.append(f"{label} cannot be resolved: {path}: {error}")
        return None


def unsafe_installed_ancestor(installed: Path, relative: str) -> str | None:
    current = installed
    components = Path(relative).parts[:-1]
    for component in components:
        current = current / component
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            return None
        except OSError as error:
            return f"installed ancestor cannot be inspected: {current}: {error}"
        if stat.S_ISLNK(metadata.st_mode):
            return f"installed ancestor is a symlink: {current}"
        if not stat.S_ISDIR(metadata.st_mode):
            return f"installed ancestor is not a directory: {current}"
    return None


def regular_tree_inventory(root: Path, label: str = "installed") -> tuple[set[str], list[str]]:
    """List regular files without following directory or file symlinks."""
    files: set[str] = set()
    problems: list[str] = []
    pending: list[tuple[Path, str]] = [(root, "")]
    while pending:
        directory, prefix = pending.pop()
        try:
            with os.scandir(directory) as scanner:
                entries = sorted(scanner, key=lambda entry: entry.name)
        except OSError as error:
            location = prefix or "."
            problems.append(f"{label} directory cannot be inventoried: {location}: {error}")
            continue
        for entry in entries:
            relative = f"{prefix}/{entry.name}" if prefix else entry.name
            try:
                if entry.is_symlink():
                    problems.append(f"{label} entry is a symlink: {relative}")
                elif entry.name in NON_PAYLOAD_NAMES or entry.name.endswith(NON_PAYLOAD_SUFFIXES):
                    continue
                elif entry.is_dir(follow_symlinks=False):
                    if entry.name in NON_PAYLOAD_DIRS:
                        continue
                    pending.append((Path(entry.path), relative))
                elif entry.is_file(follow_symlinks=False):
                    files.add(relative)
                else:
                    problems.append(f"{label} entry has an unsafe type: {relative}")
            except OSError as error:
                problems.append(f"{label} entry cannot be inventoried: {relative}: {error}")
    return files, problems


def check_known_conflicts(
    sources: list[tuple[Source, str]], failures: list[str]
) -> None:
    emitted: set[tuple[str, Path]] = set()
    for source, text in sources:
        normalized = normalized_visible(text)
        for label, fragments in LEGACY_CONFLICT_FINGERPRINTS.items():
            if any(fragment in normalized for fragment in fragments):
                key = (label, source.path)
                if key not in emitted:
                    failures.append(
                        "statically reachable legacy fingerprint candidate "
                        f"'{label}' in {source.path}; provenance: {' | '.join(source.chain)}"
                    )
                    emitted.add(key)


def check_marker_block(global_path: Path, global_text: str, failures: list[str]) -> None:
    begins = [match.start() for match in re.finditer(re.escape(BEGIN_MARKER), global_text)]
    ends = [match.start() for match in re.finditer(re.escape(END_MARKER), global_text)]
    if len(begins) != 1:
        failures.append("global begin marker count is not 1")
    if len(ends) != 1:
        failures.append("global end marker count is not 1")
    if len(begins) != 1 or len(ends) != 1:
        return
    begin, end = begins[0], ends[0]
    if begin >= end:
        failures.append("global guardpack markers are reversed")
        return
    managed = global_text[begin + len(BEGIN_MARKER) : end]
    managed_lines = [line.strip() for line in managed.splitlines() if line.strip()]
    if managed_lines != [EXPECTED_IMPORT]:
        failures.append(f"managed block must contain only the exact v{VERSION} core import")
    try:
        expected_path = resolve_import(global_path, EXPECTED_IMPORT[1:])
    except (OSError, RuntimeError) as error:
        failures.append(f"managed v{VERSION} core import cannot be resolved: {error}")
        return
    direct_expected: list[str] = []
    for raw in import_tokens(global_text):
        try:
            resolved = resolve_import(global_path, raw)
        except (OSError, RuntimeError) as error:
            failures.append(f"global direct import cannot be resolved: @{raw}: {error}")
            continue
        if resolved == expected_path:
            direct_expected.append(raw)
    if len(direct_expected) != 1:
        failures.append(f"global v{VERSION} core direct import count is not 1")
    all_guardpack_cores = [raw for raw in import_tokens(global_text) if is_guardpack_core_import(raw)]
    if all_guardpack_cores != [EXPECTED_IMPORT[1:]]:
        failures.append("global memory has a guardpack core import outside or beyond the managed block")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--global-claude", type=Path)
    parser.add_argument("--installed", type=Path)
    parser.add_argument(
        "--config-root",
        type=Path,
        help="Claude config root whose auto-invocable skills and installed plugins should be scanned",
    )
    parser.add_argument("--cwd", type=Path, help="project whose memory hierarchy should be scanned")
    parser.add_argument(
        "--rules-dir", type=Path, action="append", default=[], help="additional rules directory"
    )
    args = parser.parse_args()

    failures: list[str] = []
    warnings: list[str] = []
    if args.config_root is not None:
        # A beginner usually passes only --config-root. Derive the global memory and the
        # installed copy from it so a missing/broken core import is reported as FAIL instead
        # of a PASS that only covered routing candidates.
        derived_root = args.config_root.expanduser()
        if not derived_root.is_absolute():
            derived_root = Path.cwd() / derived_root
        derived_global = derived_root / "CLAUDE.md"
        derived_installed = derived_root / "guardpack" / "versions" / VERSION
        core_present = derived_global.exists() or derived_installed.exists()
        if args.global_claude is None and args.installed is None and not core_present:
            warnings.append(
                f"CORE-NOT-INSTALLED: neither CLAUDE.md nor guardpack/versions/{VERSION} exists "
                f"under {derived_root}; the global core was not checked"
            )
        else:
            if args.global_claude is None:
                args.global_claude = derived_global
                warnings.append(f"--global-claude derived from --config-root: {derived_global}")
            if args.installed is None:
                args.installed = derived_installed
                warnings.append(f"--installed derived from --config-root: {derived_installed}")
    pack = resolve_cli_path(args.pack, "pack path", failures)
    if pack is None:
        for item in failures:
            print(f"FAIL: {item}")
        print(f"RESULT: FAIL ({len(failures)} static issue(s))")
        return 1

    for relative in REQUIRED:
        if not (pack / relative).is_file():
            failures.append(f"missing required file: {relative}")

    texts: dict[str, str] = {}
    for path in sorted(pack.glob("*.md")):
        text = read_utf8(path, failures)
        if text is None:
            continue
        texts[path.name] = text
        if "\x00" in text or any(char in text for char in ZERO_WIDTH):
            failures.append(f"hidden control/zero-width character: {path.name}")

    readme = texts.get("README.md", "")
    core = texts.get("00-글로벌-코어.md", "")
    tests = texts.get("09-행동-회귀-테스트.md", "")

    pilot_count_claims = (
        ("09-행동-회귀-테스트.md", tests, re.compile(r"(\d+) case×2조건×3회")),
        (
            "docs/EVALUATION.md",
            read_utf8(pack / "docs" / "EVALUATION.md", failures) or "",
            re.compile(r"선택한 (\d+)개 실행 fixture|(\d+)개 case pilot 도구"),
        ),
    )
    for relative, body, pattern in pilot_count_claims:
        for match in pattern.findall(body):
            raw_count = next((value for value in match if value), match) if isinstance(match, tuple) else match
            if int(raw_count) != OFFICIAL_PILOT_CASE_COUNT:
                failures.append(
                    f"{relative} pilot case count is {raw_count}, expected "
                    f"{OFFICIAL_PILOT_CASE_COUNT}"
                )

    if f"v{VERSION}" not in readme:
        failures.append(f"README version does not match {VERSION}")
    if not core or CORE_POLICY_BASELINE_VERSION not in core.splitlines()[0]:
        failures.append(
            "core header does not identify the frozen policy baseline "
            f"{CORE_POLICY_BASELINE_VERSION}"
        )
    if len(core.splitlines()) > 120:
        failures.append(f"global core is too long: {len(core.splitlines())} lines")
    visible_core = visible_markdown(core)
    for signal in REQUIRED_CORE_SIGNALS:
        if signal not in visible_core:
            failures.append(f"core missing regression signal: {signal}")

    expected_ids = {f"T{number:02d}" for number in range(1, 31)}
    visible_tests = visible_markdown(tests)
    row_ids = TEST_ROW.findall(visible_tests)
    row_counts = Counter(row_ids)
    missing_ids = sorted(expected_ids - row_counts.keys())
    duplicate_ids = sorted(test_id for test_id, count in row_counts.items() if count != 1)
    unexpected_ids = sorted(row_counts.keys() - expected_ids)
    if missing_ids:
        failures.append("behavior test rows missing: " + ", ".join(missing_ids))
    if duplicate_ids:
        failures.append("behavior test rows duplicated: " + ", ".join(duplicate_ids))
    if unexpected_ids:
        failures.append("unexpected behavior test rows: " + ", ".join(unexpected_ids))
    for line in visible_tests.splitlines():
        if TEST_ROW.match(line):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) != 4 or any(not cell for cell in cells):
                failures.append(f"malformed behavior test row: {line[:80]}")

    case_ids: list[str] = []
    cases_path = pack / "behavior-fixtures" / "cases.jsonl"
    if cases_path.is_file():
        cases_text = read_utf8(cases_path, failures)
        for line_number, line in enumerate(
            cases_text.splitlines() if cases_text is not None else [], 1
        ):
            if not line.strip():
                continue
            try:
                case = strict_json_loads(line)
            except (json.JSONDecodeError, ValueError) as error:
                failures.append(f"invalid behavior case JSON at line {line_number}: {error}")
                continue
            if not isinstance(case, dict):
                failures.append(f"behavior case line {line_number} is not an object")
                continue
            missing_fields = sorted(BEHAVIOR_CASE_FIELDS - case.keys())
            if missing_fields:
                failures.append(
                    f"behavior case line {line_number} missing fields: {', '.join(missing_fields)}"
                )
            case_id = case.get("id")
            if isinstance(case_id, str):
                case_ids.append(case_id)
            if not isinstance(case.get("setup"), str) or not case.get("setup", "").strip():
                failures.append(f"behavior case line {line_number} has no setup string")
            observations = case.get("observe")
            if (
                not isinstance(observations, list)
                or not observations
                or any(not isinstance(item, str) or not item.strip() for item in observations)
            ):
                failures.append(f"behavior case line {line_number} has no observation list")
            if not isinstance(case.get("prompt"), str) or not case.get("prompt", "").strip():
                failures.append(f"behavior case line {line_number} has no prompt")
            if case.get("safe_fixture_only") is not True:
                failures.append(
                    f"behavior case line {line_number} must require a safe isolated fixture"
                )
        case_counts = Counter(case_ids)
        missing_cases = sorted(expected_ids - case_counts.keys())
        duplicate_cases = sorted(case_id for case_id, count in case_counts.items() if count != 1)
        unexpected_cases = sorted(case_counts.keys() - expected_ids)
        if missing_cases:
            failures.append("behavior fixture cases missing: " + ", ".join(missing_cases))
        if duplicate_cases:
            failures.append("behavior fixture cases duplicated: " + ", ".join(duplicate_cases))
        if unexpected_cases:
            failures.append("unexpected behavior fixture cases: " + ", ".join(unexpected_cases))

    plan_schema_path = pack / "behavior-fixtures" / "evaluation-plan.schema.json"
    if plan_schema_path.is_file():
        plan_schema_text = read_utf8(plan_schema_path, failures)
        if plan_schema_text is not None:
            try:
                plan_schema = strict_json_loads(plan_schema_text)
            except (json.JSONDecodeError, ValueError) as error:
                failures.append(f"invalid evaluation-plan schema JSON: {error}")
                plan_schema = None
        else:
            plan_schema = None
        if isinstance(plan_schema, dict):
            properties = plan_schema.get("properties")
            if not isinstance(properties, dict):
                failures.append("evaluation-plan schema properties must be an object")
            else:
                conditions = properties.get("conditions")
                repeats = properties.get("repeats")
                plan_cases = properties.get("cases")
                schedule = properties.get("schedule")
                treatments = properties.get("treatments")
                fixed_contract = (
                    isinstance(conditions, dict)
                    and conditions.get("const") == ["no_pack", "full_pack"]
                    and isinstance(repeats, dict)
                    and repeats.get("const") == 3
                    and isinstance(plan_cases, dict)
                    and plan_cases.get("minItems") == OFFICIAL_PILOT_CASE_COUNT
                    and plan_cases.get("maxItems") == OFFICIAL_PILOT_CASE_COUNT
                    and isinstance(schedule, dict)
                    and schedule.get("minItems") == OFFICIAL_PILOT_CELL_COUNT
                    and schedule.get("maxItems") == OFFICIAL_PILOT_CELL_COUNT
                    and isinstance(treatments, dict)
                    and treatments.get("minProperties") == 2
                    and treatments.get("maxProperties") == 2
                )
                if not fixed_contract:
                    failures.append(
                        "evaluation-plan schema does not lock the official 7x2x3 pilot"
                    )

    schema_path = pack / "behavior-fixtures" / "run-record.schema.json"
    if schema_path.is_file():
        schema_text = read_utf8(schema_path, failures)
        if schema_text is not None:
            try:
                schema = strict_json_loads(schema_text)
            except (json.JSONDecodeError, ValueError) as error:
                failures.append(f"invalid run-record schema JSON: {error}")
                schema = None
        else:
            schema = None
        if schema is not None:
            raw_required = schema.get("required", []) if isinstance(schema, dict) else []
            if not isinstance(raw_required, list) or any(
                not isinstance(item, str) for item in raw_required
            ):
                failures.append("run-record schema required must be an array of strings")
                declared: set[str] = set()
            else:
                declared = set(raw_required)
            missing_record_fields = sorted(RUN_RECORD_REQUIRED - declared)
            if missing_record_fields:
                failures.append(
                    "run-record schema missing required fields: " + ", ".join(missing_record_fields)
                )
            raw_properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
            properties = raw_properties if isinstance(raw_properties, dict) else {}
            if not isinstance(raw_properties, dict):
                failures.append("run-record schema properties must be an object")
            expected_types = {
                "run_id": "string",
                "case_id": "string",
                "case_contract_hash": "string",
                "oracle_hash": "string",
                "condition": "string",
                "condition_artifact_hash": "string",
                "repeat": "integer",
                "condition_order": "array",
                "condition_position": "integer",
                "started_at": "string",
                "session_id": "string",
                "fresh_session": "boolean",
                "config_root_id": "string",
                "isolated_config_root": "boolean",
                "state_reset_verified": "boolean",
                "observations": "object",
                "evidence": "array",
                "verdict": "string",
            }
            for field, expected_type in expected_types.items():
                declaration = properties.get(field, {})
                if not isinstance(declaration, dict):
                    declaration = {}
                if declaration.get("type") != expected_type:
                    failures.append(
                        f"run-record schema field {field} must declare type {expected_type}"
                    )
            case_declaration = properties.get("case_id", {})
            case_pattern = case_declaration.get("pattern", "") if isinstance(case_declaration, dict) else ""
            try:
                compiled_case_pattern = re.compile(case_pattern)
            except (re.error, TypeError) as error:
                failures.append(f"run-record case_id pattern is invalid: {error}")
            else:
                if any(compiled_case_pattern.fullmatch(case_id) is None for case_id in expected_ids):
                    failures.append("run-record case_id pattern does not cover T01-T30")
                if compiled_case_pattern.fullmatch("T31") is not None:
                    failures.append("run-record case_id pattern accepts unexpected T31")
            pass_fail_gate = None
            raw_gates = schema.get("allOf", []) if isinstance(schema, dict) else []
            gates = raw_gates if isinstance(raw_gates, list) else []
            if not isinstance(raw_gates, list):
                failures.append("run-record schema allOf must be an array")
            for gate in gates:
                if not isinstance(gate, dict):
                    continue
                if_clause = gate.get("if", {})
                if not isinstance(if_clause, dict):
                    continue
                if_properties = if_clause.get("properties", {})
                if not isinstance(if_properties, dict):
                    continue
                verdict_rule = if_properties.get("verdict", {})
                verdict_enum = verdict_rule.get("enum", []) if isinstance(verdict_rule, dict) else []
                if (
                    isinstance(verdict_enum, list)
                    and all(isinstance(item, str) for item in verdict_enum)
                    and set(verdict_enum) == {"pass", "fail"}
                ):
                    then_clause = gate.get("then", {})
                    then_properties = (
                        then_clause.get("properties", {})
                        if isinstance(then_clause, dict)
                        else {}
                    )
                    pass_fail_gate = then_properties if isinstance(then_properties, dict) else {}
                    break
            required_gate_rules = {
                "fresh_session": {"const": True},
                "isolated_config_root": {"const": True},
                "state_reset_verified": {"const": True},
                "user_outcome": {"minLength": 1},
                "evidence": {"minItems": 1},
            }
            if not isinstance(pass_fail_gate, dict) or any(
                pass_fail_gate.get(field) != rule for field, rule in required_gate_rules.items()
            ):
                failures.append("run-record schema lacks the pass/fail evidence and isolation gate")

    all_pack_text = "\n".join(texts.values())
    if "분기정책 §" in all_pack_text:
        failures.append("dangling legacy section reference: 분기정책 §")

    roots: list[tuple[Path, str]] = []
    if args.global_claude:
        global_path = lexical_cli_path(args.global_claude, "global memory path", failures)
        if global_path is not None:
            try:
                metadata = global_path.lstat()
            except FileNotFoundError:
                metadata = None
            except OSError as error:
                failures.append(f"global memory cannot be inspected: {global_path}: {error}")
                metadata = None
            if metadata is not None and stat.S_ISLNK(metadata.st_mode):
                failures.append(f"global memory is a symlink: {global_path}")
            elif metadata is not None and (
                not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
            ):
                failures.append(f"global memory is not a single-link regular file: {global_path}")
            else:
                global_text = read_utf8(global_path, failures)
                if global_text is not None:
                    check_marker_block(global_path, global_text, failures)
                    roots.append((global_path, "user memory"))
                    roots.extend(unscoped_rules(global_path.parent / "rules", warnings))
    else:
        warnings.append("user global memory/imports were not checked")

    for rules_dir in args.rules_dir:
        resolved_rules = lexical_cli_path(rules_dir, "rules directory", failures)
        if resolved_rules is not None:
            if resolved_rules.is_symlink():
                failures.append(f"rules directory is a symlink: {resolved_rules}")
            else:
                roots.extend(unscoped_rules(resolved_rules, warnings))
    if args.cwd:
        cwd = lexical_cli_path(args.cwd, "cwd", failures)
        if cwd is not None:
            if not cwd.is_dir():
                failures.append(f"cwd is not a directory: {cwd}")
            else:
                roots.extend(project_memory_roots(cwd, warnings))
    else:
        warnings.append("project/local memory hierarchy was not checked; pass --cwd")

    if roots:
        sources = collect_import_graph(roots, failures)
        check_known_conflicts(sources, failures)

    if args.config_root:
        try:
            routing_root = args.config_root.expanduser()
            if not routing_root.is_absolute():
                routing_root = Path.cwd() / routing_root
            warnings.extend(scan_routing_candidates(routing_root, pack, args.cwd))
        except (OSError, RuntimeError) as error:
            warnings.append(
                f"ROUTING-SCAN-INCOMPLETE: config root cannot be inspected: {args.config_root}: {error}"
            )
    else:
        warnings.append("routing candidates were not checked; pass --config-root")

    if args.installed:
        installed = lexical_cli_path(args.installed, "installed path", failures)
        if installed is not None:
            if installed.is_symlink():
                failures.append(f"installed root is a symlink: {installed}")
            elif not installed.is_dir():
                failures.append(f"installed root is not a directory: {installed}")
            else:
                installed_files, inventory_failures = regular_tree_inventory(installed)
                failures.extend(inventory_failures)
                required_files = set(REQUIRED)
                for relative in sorted(required_files - installed_files):
                    failures.append(f"installed file missing: {relative}")
                for relative in sorted(installed_files - required_files):
                    failures.append(f"installed extra file: {relative}")
                ancestor_failures: set[str] = set()
                for relative in REQUIRED:
                    source = pack / relative
                    target = installed / relative
                    unsafe = unsafe_installed_ancestor(installed, relative)
                    if unsafe is not None:
                        if unsafe not in ancestor_failures:
                            failures.append(unsafe)
                            ancestor_failures.add(unsafe)
                        continue
                    try:
                        if target.is_symlink():
                            failures.append(f"installed path is a symlink: {relative}")
                        elif not target.is_file():
                            failures.append(f"installed file missing: {relative}")
                        elif target.stat().st_nlink > 1:
                            failures.append(f"installed path is a hard link: {relative}")
                        elif source.is_file() and sha256(source) != sha256(target):
                            failures.append(f"installed hash mismatch: {relative}")
                    except OSError as error:
                        failures.append(f"installed file could not be verified: {relative}: {error}")
    else:
        warnings.append("installed copy hashes were not checked")

    warnings.append(
        "statically reachable fingerprints are conservative candidates, not active/semantic proof; "
        "managed policy, excludes, setting sources, auto memory, path-scoped/lazy memory and actual "
        "InstructionsLoaded events need separate audit"
    )
    warnings.append("LLM behavior and sandbox/permission/hook enforcement require separate tests")

    for item in failures:
        print(f"FAIL: {item}")
    for item in warnings:
        print(f"WARN: {item}")
    if failures:
        print(f"RESULT: FAIL ({len(failures)} static issue(s))")
        return 1
    if args.global_claude is None:
        print("RESULT: PASS (partial; user global memory/imports were not checked)")
        return 0
    print("RESULT: PASS (structural checks only)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
