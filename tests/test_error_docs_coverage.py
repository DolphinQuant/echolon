"""Every code in ERROR_CATALOG has a corresponding docs/errors/{code}.md page."""
from pathlib import Path

from echolon.errors import ERROR_CATALOG


def test_every_code_has_docs_page():
    repo_root = Path(__file__).parent.parent
    docs_dir = repo_root / "docs" / "errors"
    missing = [code for code in ERROR_CATALOG if not (docs_dir / f"{code}.md").exists()]
    assert not missing, f"Catalog codes missing docs pages: {missing}"


def test_index_references_every_code():
    """docs/errors/README.md must mention every catalog code (by its filename
    or codename) so a reader browsing the index sees the full catalog."""
    repo_root = Path(__file__).parent.parent
    index = (repo_root / "docs" / "errors" / "README.md").read_text()
    missing = [code for code in ERROR_CATALOG if code not in index]
    assert not missing, f"Index README missing catalog codes: {missing}"
