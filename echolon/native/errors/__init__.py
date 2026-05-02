"""Echolon error catalog — programmatic access to error documentation.

Phase F-9a: error markdown moved into the package at
``echolon/native/errors/codes/`` (was ``docs/errors/``). Ships in the wheel
via the ``echolon/native/errors/codes/*.md`` artifact in pyproject.toml.

Phase F-10a: ``ErrorDoc.what`` and ``ErrorDoc.why`` are sourced FROM THE
REGISTRY (``echolon.errors.ERROR_CATALOG``), not parsed from markdown.
This eliminates the parallel hand-maintained renderings that previously
allowed drift between the registry's glossary phrasing and the markdown's
paragraph-form lead. The markdown's ``## Why this error fires`` (or
``## Why``) sections remain — they're now treated as supplementary
long-form prose, exposed via ``ErrorDoc.long_form_markdown``, not as the
source of structured ``what``/``why`` fields.

Long-form sections still parsed for back-compat (``fix``, ``example``,
``common_causes``, ``related``), but the parser is best-effort: if a
section is missing or uses an unrecognized header, the field is empty
and ``long_form_markdown`` carries the original body verbatim.
"""
from dataclasses import dataclass
from pathlib import Path

from echolon.errors import ERROR_CATALOG


_DOCS_ROOT = Path(__file__).parent / "codes"


# Map header text (lowercased, whitespace → underscore) to canonical
# section name. ``what`` / ``why`` deliberately omitted — those come from
# the registry now, not from markdown.
_HEADER_ALIASES: dict[str, str] = {
    "fix": "fix",
    "common_causes": "common_causes",
    "related": "related",
    "related_codes": "related",
    "example": "example",
}

_SECTIONS = ("fix", "common_causes", "related", "example")


@dataclass
class ErrorDoc:
    code: str
    what: str                  # from ERROR_CATALOG[code]["what"]
    why: str                   # from ERROR_CATALOG[code]["why"]
    fix: str                   # parsed from markdown ## Fix
    common_causes: str         # parsed from markdown ## Common Causes
    related: str               # parsed from markdown ## Related / ## Related codes
    example: str               # parsed from markdown ## Example
    long_form_markdown: str    # whole markdown body — parser-resilience fallback
    raw_markdown: str          # alias of long_form_markdown for back-compat


def get_error_doc(code: str) -> ErrorDoc:
    """Load the parsed error doc for a given error code.

    ``what`` and ``why`` come from ``ERROR_CATALOG`` (the registry); the
    markdown is consulted only for long-form sections (``fix``,
    ``example``, ``common_causes``, ``related``) and the verbatim body.
    A code with no markdown file is still returned with structured
    ``what``/``why`` populated from the registry.

    Args:
        code: Error code like 'VAL-001' or 'IND-003'.

    Raises:
        KeyError: if the code is not in ``ERROR_CATALOG``.
        FileNotFoundError: if the code is in the registry but its
            markdown page is missing (a packaging bug — every registry
            code should have a corresponding ``codes/{code}.md``).
    """
    if code not in ERROR_CATALOG:
        raise KeyError(f"Unknown error code: {code}. See ERROR_CATALOG for the full list.")
    reg = ERROR_CATALOG[code]
    path = _DOCS_ROOT / f"{code}.md"
    if not path.is_file():
        raise FileNotFoundError(
            f"Code {code} is in the registry but its markdown page is "
            f"missing at {path}. This is a packaging bug — file a ticket."
        )
    raw = path.read_text()

    sections: dict[str, str] = {name: "" for name in _SECTIONS}
    current: str | None = None
    buffer: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            if current is not None:
                sections[current] = "\n".join(buffer).strip()
            header = stripped[3:].lower().strip().replace(" ", "_")
            current = _HEADER_ALIASES.get(header)
            buffer = []
        elif current is not None:
            buffer.append(line)
    if current is not None:
        sections[current] = "\n".join(buffer).strip()

    return ErrorDoc(
        code=code,
        what=reg["what"],
        why=reg["why"],
        long_form_markdown=raw,
        raw_markdown=raw,
        **sections,
    )


__all__ = ["ErrorDoc", "get_error_doc"]
