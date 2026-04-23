"""Phase B2 — echolon-mcp stdio live-spawn smoke.

Spawns the ``echolon-mcp`` console script as a subprocess and invokes the new
catalog-backed indicator tools through the real MCP protocol (JSON-RPC over
stdin/stdout). Verifies the serialization path works end-to-end, not just the
in-process Python call.

Skipped when the ``echolon-mcp`` console script isn't on PATH (e.g. when echolon
isn't installed into the test env).
"""
import asyncio
import json
import shutil

import pytest


_HAS_MCP_SERVER = shutil.which("echolon-mcp") is not None


@pytest.mark.skipif(not _HAS_MCP_SERVER, reason="echolon-mcp not on PATH")
def test_stdio_validate_indicator_list_returns_structured_error():
    """Spawn echolon-mcp; call validate_indicator_list with an unknown name;
    assert the response is a structured error payload (not a raise)."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def run():
        params = StdioServerParameters(command="echolon-mcp", args=[])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Tool registration check
                tools = await session.list_tools()
                names = {t.name for t in tools.tools}
                for expected in (
                    "list_indicators",
                    "indicator_info",
                    "validate_indicator_list",
                    "suggest_similar",
                ):
                    assert expected in names, f"missing {expected} in stdio tool list"

                # Call validate_indicator_list with a deliberately unknown name
                result = await session.call_tool(
                    "validate_indicator_list",
                    arguments={"payload_json": json.dumps({"fake_rsi": {}})},
                )
                # FastMCP wraps return values; pull the parsed JSON payload.
                # result.content is a list of Content objects; TextContent has .text
                assert result.content, "expected non-empty content"
                text = result.content[0].text
                payload = json.loads(text)
                assert payload["valid"] is False
                assert len(payload["errors"]) == 1
                err = payload["errors"][0]
                assert err["field"] == "fake_rsi"
                assert "rsi" in err["suggestion"]

    asyncio.run(run())


@pytest.mark.skipif(not _HAS_MCP_SERVER, reason="echolon-mcp not on PATH")
def test_stdio_list_indicators_returns_many_names():
    """list_indicators through stdio returns the full catalog (170+).

    FastMCP serializes a ``list[str]`` as N separate TextContent entries
    (one per element), not one JSON-wrapped content.
    """
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def run():
        params = StdioServerParameters(command="echolon-mcp", args=[])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("list_indicators", arguments={})
                names = [c.text for c in result.content]
                assert len(names) >= 170
                assert "rsi" in names
                assert "obv" in names

    asyncio.run(run())
