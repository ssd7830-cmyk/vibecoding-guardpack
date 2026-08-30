from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / "skills"
sys.path.insert(0, str(ROOT))
import verify_guardpack as verifier  # noqa: E402

EXPECTED_SOURCES = {
    "guardpack-safety-audit": ("01-비가역-가드.md",),
    "guardpack-completion-check": ("02-완료-검증-가드.md",),
    "guardpack-debug-evidence": ("03-진단-수리-분리.md",),
    "guardpack-context-intent": ("04-오염-차단.md", "06-되묻기-기록.md"),
    "guardpack-evidence-review": (
        "05-정직-보고.md",
        "07-한국어-가드.md",
        "08-분기-플레이북.md",
    ),
    "guardpack": (),
}

NAME_PATTERN = re.compile(r"^[a-z0-9-]{1,64}$")
SOURCE_PATTERN = re.compile(
    r"\$\{CLAUDE_PLUGIN_ROOT\}/(0[1-8]-[^`\s]+\.md)"
)


def parse_frontmatter(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise AssertionError(f"missing opening frontmatter marker: {path}")
    try:
        end = lines.index("---", 1)
    except ValueError as error:
        raise AssertionError(f"missing closing frontmatter marker: {path}") from error

    fields: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise AssertionError(f"unsupported frontmatter line in {path}: {line!r}")
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key in fields:
            raise AssertionError(f"duplicate frontmatter key in {path}: {key}")
        fields[key] = value
    return fields, "\n".join(lines[end + 1 :])


class SkillsContractTests(unittest.TestCase):
    def skill_paths(self) -> list[Path]:
        return sorted(SKILLS_ROOT.glob("*/SKILL.md"))

    def test_exact_skill_layout(self) -> None:
        expected_paths = {
            SKILLS_ROOT / name / "SKILL.md" for name in EXPECTED_SOURCES
        }
        actual_paths = set(SKILLS_ROOT.glob("**/SKILL.md"))
        self.assertEqual(actual_paths, expected_paths)

    def test_frontmatter_and_unique_names(self) -> None:
        names: list[str] = []
        for path in self.skill_paths():
            fields, _ = parse_frontmatter(path)
            for required in (
                "name",
                "description",
                "disable-model-invocation",
                "user-invocable",
            ):
                self.assertIn(required, fields, f"{path}: missing {required}")

            name = fields["name"]
            names.append(name)
            self.assertEqual(name, path.parent.name)
            self.assertRegex(name, NAME_PATTERN)
            self.assertGreaterEqual(len(fields["description"]), 40)
            self.assertLessEqual(len(fields["description"]), 1536)
            self.assertIn(fields["disable-model-invocation"], {"true", "false"})
            self.assertEqual(fields["user-invocable"], "true")

            expected_manual = name == "guardpack-safety-audit"
            self.assertEqual(
                fields["disable-model-invocation"] == "true",
                expected_manual,
                f"{name}: only the safety audit may be manual-only",
            )

        self.assertEqual(len(names), len(set(names)), "duplicate skill name")
        self.assertEqual(set(names), set(EXPECTED_SOURCES))

    def test_canonical_paths_exist_and_have_one_owner(self) -> None:
        owners: dict[str, list[str]] = {}
        for path in self.skill_paths():
            fields, body = parse_frontmatter(path)
            name = fields["name"]
            references = tuple(SOURCE_PATTERN.findall(body))
            self.assertEqual(
                set(references),
                set(EXPECTED_SOURCES[name]),
                f"{name}: canonical source routing drift",
            )
            for source in references:
                self.assertTrue((ROOT / source).is_file(), f"missing canonical source: {source}")
                owners.setdefault(source, []).append(name)

        expected_all = {source for sources in EXPECTED_SOURCES.values() for source in sources}
        self.assertEqual(set(owners), expected_all)
        for source, source_owners in owners.items():
            self.assertEqual(source_owners, [source_owners[0]], f"multiple owners for {source}")

    def test_safety_audit_handoff_is_manual_separate_and_fail_closed(self) -> None:
        skill_path = SKILLS_ROOT / "guardpack-safety-audit" / "SKILL.md"
        fields, skill_body = parse_frontmatter(skill_path)
        canonical = (ROOT / "01-비가역-가드.md").read_text(encoding="utf-8")
        quickstart = (ROOT / "docs" / "QUICKSTART.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertEqual(fields["disable-model-invocation"], "true")
        for status in ("실행 가능", "검토 대상 없음", "범위 누락", "미실행", "미지원"):
            self.assertIn(status, skill_body)
            self.assertIn(status, quickstart)
        for signal in (
            "/security-review",
            "origin/HEAD",
            "staged",
            "unstaged",
            "untracked",
            "자동",
        ):
            self.assertIn(signal, skill_body)
            self.assertIn(signal, canonical)
        self.assertIn("가드팩 안전 감사 → 사람이 `/security-review`를 별도 실행", quickstart)
        self.assertIn("claude --plugin-dir \"/절대경로/바이브코딩-가드팩\"", quickstart)
        self.assertNotIn("바이브코딩-가드팩-v2.3-stage", quickstart)
        self.assertNotIn(
            "/vibecoding-guardpack:guardpack-safety-audit /security-review",
            quickstart,
        )
        self.assertIn("한쪽의 문제 미발견은 다른 층의", readme)

    def test_plugin_manifest_has_stable_namespace(self) -> None:
        manifest_path = ROOT / ".claude-plugin" / "plugin.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "vibecoding-guardpack")
        self.assertEqual(manifest["version"], "2.3.7")
        self.assertTrue(manifest.get("description"))
        self.assertTrue(manifest.get("author", {}).get("name"))

    def test_marketplace_points_to_this_plugin_root(self) -> None:
        marketplace_path = ROOT / ".claude-plugin" / "marketplace.json"
        marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
        self.assertEqual(marketplace["name"], "vibecoding-guardpack-local")
        self.assertTrue(marketplace.get("owner", {}).get("name"))
        self.assertTrue(marketplace.get("description"))
        self.assertEqual(len(marketplace["plugins"]), 1)
        entry = marketplace["plugins"][0]
        self.assertEqual(entry["name"], "vibecoding-guardpack")
        self.assertEqual(entry["source"], "./")
        self.assertEqual(entry["version"], "2.3.7")

    def test_forbidden_vocabulary_is_absent_from_routing_assets(self) -> None:
        forbidden = ("onto" + "logy", "\uc628\ud1a8\ub85c\uc9c0")
        asset_paths = self.skill_paths() + [
            ROOT / ".claude-plugin" / "plugin.json",
            ROOT / ".claude-plugin" / "marketplace.json",
            ROOT / "docs" / "QUICKSTART.md",
        ]
        for path in asset_paths:
            text = path.read_text(encoding="utf-8").casefold()
            for term in forbidden:
                self.assertNotIn(term.casefold(), text, f"forbidden vocabulary in {path}")

    def test_known_routing_policy_registry_matches_readme_table(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        expected = {
            "audit": ("T19", "08 §1·§5"),
            "feature-dev": ("T02·T19", "06 §2·08 §1"),
            "claude-md-improver": ("T10·T19", "04 §1·06 §6"),
            "revise-claude-md": ("T10", "04 §1·06 §6"),
        }
        self.assertEqual(set(verifier.KNOWN_ROUTING_POLICIES), set(expected))
        for name, signals in expected.items():
            row = next(
                line for line in readme.splitlines() if line.startswith(f"| `{name}` |")
            )
            for signal in signals:
                self.assertIn(signal, row)
            contract, _ = verifier.KNOWN_ROUTING_POLICIES[name]
            for signal in signals:
                self.assertIn(signal, contract)

    def test_every_routing_diagnostic_is_documented_for_students_and_release(self) -> None:
        diagnostics = {
            "ROUTING-POLICY",
            "ROUTING-OVERLAP",
            "ROUTING-SCAN-INCOMPLETE",
            "GUARDPACK-PLUGIN-VERSION-MISMATCH",
            "GUARDPACK-PLUGIN-CONTENT-MISMATCH",
        }
        for relative in ("README.md", "docs/QUICKSTART.md", "docs/release-helper.md"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(relative=relative):
                for diagnostic in diagnostics:
                    self.assertIn(diagnostic, text)


if __name__ == "__main__":
    unittest.main()
