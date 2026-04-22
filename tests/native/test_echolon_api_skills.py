"""Phase 0 gate test: every echolon symbol imported by qorka's
coding_agent has a matching SKILL.md in
echolon/native/skills/echolon_api/.

Run after Task 8 completes. The audit script from Task 6 provides
the reference set via audit_output.txt at repo root.
"""
import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "echolon" / "native" / "skills" / "echolon_api"
AUDIT_FILE = REPO_ROOT / "audit_output.txt"


def _symbol_to_skill_dirname(symbol: str) -> str:
    """Match Task 8's naming rule: last segment of the dotted path, snake_case.

    Handles consecutive capitals (e.g. WFARunner -> wfa_runner) by:
    1. Inserting underscore before uppercase that follows lowercase/digit
    2. Inserting underscore before the last capital in a sequence that precedes lowercase
    """
    last = symbol.split(".")[-1]
    # Insert underscore before uppercase that follows lowercase or digit
    converted = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", last)
    # Insert underscore before the last capital in a sequence (e.g. WFARunner -> WFA_Runner)
    converted = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", converted)
    return converted.lower()


@pytest.fixture
def audited_symbols() -> list[str]:
    if not AUDIT_FILE.is_file():
        pytest.skip("audit_output.txt not found — run scripts/audit_echolon_api_skills.py")
    raw = [line.strip() for line in AUDIT_FILE.read_text().splitlines() if line.strip()]
    # Skip the bare 'echolon' entry — not a specific symbol worth a skill
    return [s for s in raw if s != "echolon"]


def test_every_audited_symbol_has_a_skill(audited_symbols):
    missing = []
    for symbol in audited_symbols:
        expected = SKILLS_DIR / _symbol_to_skill_dirname(symbol) / "SKILL.md"
        if not expected.is_file():
            missing.append((symbol, str(expected)))
    assert not missing, (
        "Symbols without a SKILL.md:\n"
        + "\n".join(f"  {sym}  →  {path}" for sym, path in missing)
    )


def test_every_skill_has_valid_frontmatter():
    """Every SKILL.md must have a YAML frontmatter block with required keys."""
    import yaml

    required_keys = {"name", "description", "type", "primary_scope"}
    invalid = []
    for skill_md in SKILLS_DIR.rglob("SKILL.md"):
        text = skill_md.read_text()
        if not text.startswith("---\n"):
            invalid.append(f"{skill_md}: no frontmatter block")
            continue
        try:
            _, fm_text, _ = text.split("---\n", 2)
        except ValueError:
            invalid.append(f"{skill_md}: malformed frontmatter")
            continue
        try:
            fm = yaml.safe_load(fm_text)
        except yaml.YAMLError as e:
            invalid.append(f"{skill_md}: invalid yaml — {e}")
            continue
        missing_keys = required_keys - set(fm.keys())
        if missing_keys:
            invalid.append(f"{skill_md}: missing keys — {missing_keys}")

    assert not invalid, "Invalid skills:\n" + "\n".join(invalid)


def test_skills_index_contains_every_skill():
    """Every SKILL.md must have a one-line entry in SKILLS.md."""
    index = SKILLS_DIR.parent / "SKILLS.md"
    assert index.is_file(), "SKILLS.md index missing"
    index_text = index.read_text()

    missing = []
    for skill_md in SKILLS_DIR.rglob("SKILL.md"):
        rel = skill_md.relative_to(SKILLS_DIR.parent)
        rel_str = str(rel).replace("\\", "/")
        if rel_str not in index_text:
            missing.append(rel_str)

    assert not missing, "Skills not in SKILLS.md index:\n" + "\n".join(missing)


def test_migrated_qorka_skills_present():
    """The 3 qorka skills migrated in Phase 1 Task 15 must live in echolon now."""
    from pathlib import Path
    skills_root = Path(__file__).resolve().parents[2] / "echolon" / "native" / "skills" / "echolon_api"
    for skill in ("validation-backup", "code-standards", "trading-api-core"):
        skill_md = skills_root / skill / "SKILL.md"
        assert skill_md.is_file(), f"Missing SKILL.md for migrated skill: {skill}"
        text = skill_md.read_text()
        assert f"name: {skill}" in text, f"{skill}/SKILL.md frontmatter missing name field"


def test_migrated_qorka_skills_indexed_in_SKILLS_md():
    """SKILLS.md index must link each of the 3 migrated skills."""
    from pathlib import Path
    skills_md = Path(__file__).resolve().parents[2] / "echolon" / "native" / "skills" / "SKILLS.md"
    text = skills_md.read_text()
    for skill in ("validation-backup", "code-standards", "trading-api-core"):
        assert f"[{skill}](echolon_api/{skill}/SKILL.md)" in text, (
            f"SKILLS.md index missing link for migrated skill {skill!r}"
        )
