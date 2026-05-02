# Echolon

[![PyPI](https://img.shields.io/pypi/v/echolon.svg)](https://pypi.org/project/echolon/)
[![Python](https://img.shields.io/pypi/pyversions/echolon.svg)](https://pypi.org/project/echolon/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-beta-yellow.svg)](https://pypi.org/project/echolon/)

> A Python toolkit for futures trading research, built so an LLM agent can drive it directly. Scaffold a strategy, validate it, backtest it, read structured errors when something breaks. Currently focused on SHFE daily futures.

If you've asked Claude Code or Cursor to write a backtest in `backtrader` or `vectorbt`, you know how it goes: the agent invents indicator names, guesses at callback signatures, swallows errors silently. We built echolon around that failure mode. Errors carry stable codes, configs are typed Pydantic models, and the package ships an MCP server so an agent has structured tools to call instead of prose to hallucinate against.

## Install and run a backtest

```bash
pip install echolon
echolon init-strategy my_first --template minimal
echolon validate my_first/
echolon run my_first/ --instrument cu --start 2020-01-01 --end 2023-12-31
```

The `minimal` template runs end-to-end with zero trades on purpose — it's there to confirm the data, validation, and engine wiring work before you put any logic in. After that completes, open `entry.py` and put a signal in.

## Where echolon is today

v0.1.1 is deliberately narrow. What works end-to-end right now is **SHFE daily futures research**: data ingestion, indicator computation against the 217-indicator catalog, backtesting through Backtrader, Optuna TPE optimization (single + multi-objective), walk-forward analysis with deployment-readiness scoring, KMeans-based robust trial selection, and the agent surface described below.

What's in flight, roughly in order:

- SHFE intraday backtesting (data pipeline supports it; the engine pathway is being stabilized)
- Live deployment to SHFE through MiniQMT — the `deploy` CLI exists from earlier internal builds; a clean public release is being written
- Crypto perpetuals (the CCXT adapter is scaffolded but neither backtest nor live is on the near-term roadmap)
- CME futures and equities (architectural slot exists; no implementation yet)

If your work is SHFE futures research with an LLM in the loop, you can use this today. If you need crypto, US markets, or live trading, you're early — open an issue if you want to drive a particular slice and we'll talk about timing.

## What's actually AI-native about it

The package ships four things an agent can reach without reading prose:

- **An MCP server** — `echolon-mcp` exposes 22 tools over stdio. Strategy validation, the full indicator catalog, scaffold generation, error lookup, parameter codegen. Any MCP-compatible runtime can wire it in.
- **23 skill packets inside the wheel** — quick-start, component contract, indicator-naming rules, parameter architecture, the five canonical strategy shapes, plus per-API doctrine. Indexed at `echolon/native/skills/SKILLS.md`. Loaded on demand by the agent's skill runtime.
- **31 catalogued error codes** — every `EchelonError` carries a code, a parameterized fix string, and a docs URL. The traceback is structured for the agent to act on directly.
- **Three working strategy templates** — `minimal`, `momentum_breakout`, `rsi_mean_reversion`. The agent copies one and edits it, instead of writing files from scratch.

When you ask a Claude Code session with `echolon-mcp` connected to "build a trend-following strategy on copper", here's what happens: the agent calls `list_skills`, picks `patterns` and `quick_start`, calls `load_template("momentum_breakout")`, calls `list_indicators(has_lookback=True)` to confirm what's available, edits `entry.py` and `exit.py`, calls `validate_strategy_full(strategy_dir)` until everything passes, then runs the backtest. If anything breaks, it parses `[CODE-NNN]` from the traceback and calls `get_error_doc(code)`. There's no point in the loop where it has to guess.

## Wire it into your agent runtime

| Runtime | Setup |
|---|---|
| Claude Code | `claude mcp add echolon echolon-mcp` |
| Cursor | Settings → MCP Servers → add `{"echolon": {"command": "echolon-mcp"}}` |
| OpenAI Codex CLI | Add `echolon` server to `~/.codex/config.toml` |
| OpenAI Agents SDK (Python) | `MCPServerStdio(command="echolon-mcp")` |
| LangChain / LangGraph | via [`langchain-mcp-adapters`](https://pypi.org/project/langchain-mcp-adapters/) |
| CrewAI / AutoGen / others | Any [MCP-compatible](https://modelcontextprotocol.io/) client adapter |

The agent's orientation manual is [`llms.txt`](./llms.txt) — point your agent at it once and it'll know where to find everything else.

## Where to find things

Everything that matters to an agent ships inside the wheel. `pip install` and the agent has parity access — no separate docs site to fetch.

| Surface | Lives at |
|---|---|
| MCP server | `echolon-mcp` console script — call `list_tools` for live introspection |
| Skills (23) | `echolon/native/skills/` — call MCP `list_skills` / `get_skill(name)` |
| Error codes (31) | `echolon/native/errors/codes/` — call MCP `get_error_doc(code)` |
| Templates (3) | `echolon/native/templates/` — call MCP `list_templates` / `load_template(name)` |
| Patterns (5) | call MCP `list_patterns` / `get_pattern(name)` |
| CLI reference | `echolon --help` (every subcommand has `--help` too) |
| Pydantic schemas | `echolon schema BacktestConfig` (or any other config) |
| LLM orientation | [`llms.txt`](./llms.txt) |
| Release history | [CHANGELOG.md](./CHANGELOG.md) |

The Python public surface re-exports the common stuff at the top level — `echolon.quick_start`, `echolon.BacktestConfig`, `echolon.OptunaConfig`, `echolon.TradingContext`, `echolon.EchelonError`. The `api_reference` and `config_reference` skills have the typed signatures.

## What you can't do yet

Being specific so you don't get bitten:

- Only SHFE daily backtesting is production. Crypto, intraday, CME, and equities are not.
- No live trading shipped publicly yet. The next live target is SHFE through MiniQMT (Windows-only broker integration); crypto and US-market live trading aren't on the short-term roadmap.
- Optuna TPE only. No grid, no random, no Bayesian budgeting.
- Single machine. Optuna parallelism uses local cores; no distributed orchestration.
- Python 3.11+ required.
- Pre-1.0, so the public API can shift between minor versions. Breaking changes are documented in [CHANGELOG.md](./CHANGELOG.md).

## License

Apache 2.0 — see [LICENSE](LICENSE). Use freely, commercially or otherwise.

## Citation

If echolon shows up in academic work:

```bibtex
@software{echolon,
  title = {Echolon: AI-native quantitative trading engine},
  author = {DolphinQuant},
  year = {2026},
  url = {https://github.com/dolphinquant/echolon},
}
```

## Status

v0.1.1, beta, 2026. Active development. Issues and pull requests welcome at [github.com/dolphinquant/echolon](https://github.com/dolphinquant/echolon).
