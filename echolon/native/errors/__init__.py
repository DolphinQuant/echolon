"""Echolon error catalog — programmatic access to error documentation."""
from dataclasses import dataclass
from pathlib import Path


_DOCS_ROOT = Path(__file__).resolve().parents[3] / "docs" / "errors"


@dataclass
class ErrorDoc:
    code: str
    what: str
    why: str
    fix: str
    common_causes: str
    related: str
    raw_markdown: str


def get_error_doc(code: str) -> ErrorDoc:
    """Load the parsed error doc for a given error code.

    Args:
        code: Error code like 'VAL-001' or 'IND-003'.

    Raises:
        FileNotFoundError: if docs/errors/{code}.md doesn't exist.
    """
    path = _DOCS_ROOT / f"{code}.md"
    if not path.is_file():
        raise FileNotFoundError(f"No error doc for code {code} at {path}")
    raw = path.read_text()

    # Minimal markdown section parser: find "## {section}" blocks
    sections = {"what": "", "why": "", "fix": "", "common_causes": "", "related": ""}
    current = None
    buffer: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            if current and current in sections:
                sections[current] = "\n".join(buffer).strip()
            header = stripped[3:].lower().replace(" ", "_")
            current = header if header in sections else None
            buffer = []
        elif current is not None:
            buffer.append(line)
    if current and current in sections:
        sections[current] = "\n".join(buffer).strip()

    return ErrorDoc(
        code=code,
        raw_markdown=raw,
        **sections,
    )


__all__ = ["ErrorDoc", "get_error_doc"]
