"""Echolon patterns — parse docs/PATTERNS.md, expose programmatic access."""
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Pattern:
    name: str
    when_to_use: str
    key_idea: str
    files_to_customize: str
    sketch_code: str
    common_errors: str
    raw_markdown: str


_PATTERNS_MD = Path(__file__).resolve().parents[3] / "docs" / "PATTERNS.md"


def _parse_patterns() -> dict[str, Pattern]:
    """Parse docs/PATTERNS.md into a dict of Pattern objects keyed by name."""
    if not _PATTERNS_MD.is_file():
        return {}
    raw = _PATTERNS_MD.read_text()

    # Patterns are delimited by "## N. Name" or "## Name" headers
    patterns: dict[str, Pattern] = {}
    current_name: str | None = None
    current_sections: dict[str, list[str]] = {}
    current_key: str | None = None

    def flush():
        if current_name is None:
            return
        sections_joined = {k: "\n".join(v).strip() for k, v in current_sections.items()}
        patterns[current_name.lower().replace(" ", "_")] = Pattern(
            name=current_name,
            when_to_use=sections_joined.get("when to use", ""),
            key_idea=sections_joined.get("key idea", ""),
            files_to_customize=sections_joined.get("files to customize", ""),
            sketch_code=sections_joined.get("sketch", ""),
            common_errors=sections_joined.get("common errors", ""),
            raw_markdown="",  # raw slice omitted for brevity
        )

    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("## ") and not stripped.startswith("## Indicator Naming"):
            flush()
            # Trim leading number like "## 1. Trend Breakout" → "Trend Breakout"
            name = stripped[3:].lstrip("0123456789. ")
            current_name = name
            current_sections = {}
            current_key = None
        elif stripped.startswith("**") and stripped.endswith(":**") and current_name:
            # section header inside a pattern
            current_key = stripped[2:-3].lower()
            current_sections[current_key] = []
        elif current_key is not None:
            current_sections[current_key].append(line)
    flush()
    return patterns


_CACHE = _parse_patterns()


def list_patterns() -> list[str]:
    return sorted(_CACHE.keys())


def get_pattern(name: str) -> Pattern | None:
    return _CACHE.get(name.lower())


__all__ = ["Pattern", "list_patterns", "get_pattern"]
