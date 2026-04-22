"""echolon-mcp — FastMCP server that wraps the Task 10/11 programmatic APIs.

Launched via the `echolon-mcp` console script. OpenAI Agents SDK consumers
attach via `MCPServerStdio(command="echolon-mcp", args=[])`.
"""
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from echolon.indicators import catalog as _catalog
from echolon.native import patterns as _patterns
from echolon.native import templates as _templates
from echolon.native.errors import get_error_doc as _get_error_doc
from echolon.native.validation import validate_strategy as _validate_strategy


def build_server() -> FastMCP:
    """Construct and return the FastMCP server with all echolon tools registered."""
    server = FastMCP("echolon")

    @server.tool()
    def validate_strategy(path: str) -> dict:
        """Validate a strategy directory against echolon contracts.

        Args:
            path: Absolute path to the strategy directory.

        Returns a dict with keys: status ("VALID"|"INVALID"), errors (list of dicts).
        """
        result = _validate_strategy(Path(path))
        return {
            "status": result.status,
            "errors": [
                {
                    "code": e.code,
                    "what": e.what,
                    "why": e.why,
                    "fix": e.fix,
                    "docs_url": e.docs_url,
                }
                for e in result.errors
            ],
        }

    @server.tool()
    def get_error_doc(code: str) -> dict:
        """Fetch the parsed error documentation for a given error code.

        Args:
            code: Error code like 'VAL-001' or 'IND-003'.
        """
        doc = _get_error_doc(code)
        return {
            "code": doc.code,
            "what": doc.what,
            "why": doc.why,
            "fix": doc.fix,
            "common_causes": doc.common_causes,
            "related": doc.related,
        }

    @server.tool()
    def list_indicators() -> list[str]:
        """Return all indicator names shipped by echolon."""
        return _catalog.list_all()

    @server.tool()
    def indicator_info(name: str) -> dict | None:
        """Return structured info for one indicator, or None if unknown."""
        info = _catalog.info(name)
        if info is None:
            return None
        return {
            "name": info.name,
            "tier": info.tier,
            "params": info.params,
            "output_columns": info.output_columns,
        }

    @server.tool()
    def list_patterns() -> list[str]:
        """Return all canonical pattern names."""
        return _patterns.list_patterns()

    @server.tool()
    def get_pattern(name: str) -> dict | None:
        """Return a pattern's structured content, or None if unknown."""
        p = _patterns.get_pattern(name)
        if p is None:
            return None
        return {
            "name": p.name,
            "when_to_use": p.when_to_use,
            "key_idea": p.key_idea,
            "files_to_customize": p.files_to_customize,
            "sketch_code": p.sketch_code,
            "common_errors": p.common_errors,
        }

    @server.tool()
    def list_templates() -> list[str]:
        """Return all shipped strategy template names."""
        return _templates.list_templates()

    @server.tool()
    def load_template(name: str) -> dict | None:
        """Load a template's files. Returns {'name': ..., 'files': {filename: content}}."""
        tpl = _templates.load_template(name)
        if tpl is None:
            return None
        return {"name": tpl.name, "files": tpl.files}

    return server


def main():  # pragma: no cover — invoked by `echolon-mcp` console script
    from echolon._internal.structured_logging import install_structured_logging
    install_structured_logging()
    server = build_server()
    server.run()


if __name__ == "__main__":
    main()
