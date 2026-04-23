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
    def list_indicators(cluster: str | None = None) -> list[str]:
        """Return all indicator names in the echolon catalog, optionally filtered by cluster.

        Args:
            cluster: Optional cluster filter. Valid values:
                ``"indicators_with_lookback"``, ``"indicators_without_lookback"``,
                ``"indicators_with_special_params"``, ``"intraday_context_indicators"``.
                Omit for all.
        """
        return _catalog.list_all(cluster=cluster)

    @server.tool()
    def indicator_info(name: str) -> dict | None:
        """Return structured info for one indicator, or None if unknown.

        Keys: ``name``, ``cluster``, ``function``, ``file``, ``params``
        (list of ``{name, default, type}`` dicts), ``output_columns``.
        """
        info = _catalog.info(name)
        if info is None:
            return None
        return {
            "name": info.name,
            "cluster": info.cluster,
            "function": info.function,
            "file": info.file,
            "params": info.params,
            "output_columns": info.output_columns,
        }

    @server.tool()
    def indicator_params(name: str) -> list[dict] | None:
        """Return the tunable parameters for an indicator, or None if unknown.

        Convenience accessor — same as ``indicator_info(name)["params"]`` but
        skips the wrapper dict. Each entry is ``{"name": str, "default": any, "type": str}``.
        """
        info = _catalog.info(name)
        if info is None:
            return None
        return info.params

    @server.tool()
    def validate_indicator_list(payload_json: str) -> dict:
        """Validate a flat-dict ``strategy_indicator_list.json`` payload against the catalog.

        Args:
            payload_json: JSON string of the flat-dict
                (e.g. ``'{"rsi": {"timeperiod": [10, 20]}}'``).

        Returns a dict ``{"valid": bool, "errors": [{code, field, message, suggestion}]}``.
        Bad JSON surfaces as a structured error, not a raise.
        """
        import json as _json

        try:
            data = _json.loads(payload_json)
        except _json.JSONDecodeError as e:
            return {
                "valid": False,
                "errors": [{
                    "code": "IND-000",
                    "field": "<payload>",
                    "message": f"Failed to parse JSON: {e}",
                    "suggestion": [],
                }],
            }
        errors = _catalog.validate(data)
        return {"valid": not errors, "errors": errors}

    @server.tool()
    def suggest_similar(name: str, limit: int = 5) -> list[str]:
        """Return up to ``limit`` catalog names close to ``name`` (difflib + substring)."""
        return _catalog.suggest_similar(name, limit=limit)

    @server.tool()
    def generate_strategy_params(
        params_file_path: str,
        output_path: str,
        frequency: str = "interday",
    ) -> dict:
        """Generate strategy_params.py from params_to_optimize.json.

        Deterministic code generation: parses the JSON → determines parameter
        ownership across components → emits ComponentParameterTemplate classes
        + framework registration + optuna_search_space with crossover
        constraints → writes the target file. Period parameters that exceed
        the frequency-appropriate indicator cap are auto-clamped and reported.

        Args:
            params_file_path: Absolute path to ``params_to_optimize.json``.
            output_path: Absolute path to write ``strategy_params.py``.
            frequency: ``"interday"`` (caps: TEMA≤62, ADX≤93, default≤180)
                or ``"intraday"`` (caps: TEMA≤500, ADX≤750, default≤1000).

        Returns ``{"success": bool, "output_path": str, "corrections":
        [{"param", "type", "old_*", "new_*", "cap", "category", "changes"?}],
        "message": str}``. Parse / IO failures surface as
        ``success=False`` rather than raising.
        """
        from echolon.strategy.generators import (
            generate_strategy_params as _impl,
        )
        result = _impl(
            params_file_path=params_file_path,
            output_path=output_path,
            frequency=frequency,
        )
        return {
            "success": result.success,
            "output_path": result.output_path,
            "corrections": result.corrections,
            "message": result.message,
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
