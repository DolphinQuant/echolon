# Echolon

[![PyPI](https://img.shields.io/pypi/v/echolon.svg)](https://pypi.org/project/echolon/)
[![Python](https://img.shields.io/pypi/pyversions/echolon.svg)](https://pypi.org/project/echolon/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-beta-yellow.svg)](https://pypi.org/project/echolon/)
[![By DolphinQuant](https://img.shields.io/badge/by-DolphinQuant-005f87)](https://dolphinquant.com)

> 📖 [English](README.md) · [简体中文](README.zh-CN.md)

> A Python toolkit for futures trading research, built so an LLM agent can drive it directly. Scaffold a strategy, validate it, backtest it, read structured errors when something breaks. Currently focused on SHFE daily futures.

If you've asked Claude Code or Cursor to write a backtest in `backtrader` or `vectorbt`, you know how it goes: the agent invents indicator names, guesses at callback signatures, swallows errors silently. We built echolon around that failure mode. Errors carry stable codes, configs are typed Pydantic models, and the package ships an MCP server so an agent has structured tools to call instead of prose to hallucinate against.

## Install and run a backtest

## Quickstart

Echolon ships three top-level commands matching the natural newcomer arc:

| Command | Purpose | Time |
|---|---|---|
| `echolon hello` | First impression. Downloads SHFE aluminum (last 2y) via akshare + scaffolds strategy + auto-backtest. Network required. | ~30s |
| `echolon init <workspace> --market SHFE --instrument <i> --start <d> --end <d>` | Real project. Downloads market data via akshare (free, no registry), scaffolds a strategy from a bundled template, writes a workspace marker. | ~1–5 min |
| `echolon backtest single <strategy_dir>` | Iterate. Walks up from `strategy_dir` to recover context from the workspace marker; recomputes indicators and runs backtest with zero flags. | ~5–10s |

### See it work — `echolon hello`

```bash
pip install echolon
mkdir -p ~/echolon-playground && cd ~/echolon-playground
echolon hello
```

This downloads ~2 years of SHFE aluminum via akshare, scaffolds the `momentum_breakout` strategy template, writes an `.echolon-workspace.json` marker, and runs a backtest immediately:

```
./echolon-hello/
├── .echolon-workspace.json     ← marker — `echolon backtest` recovers ctx from here
├── data/                       ← YOUR inputs (curation) — see data/README.md
│   └── SHFE/al/main_contract.csv  ← roll convention; edit to change rules
├── workspace/
│   ├── data/                   ← pipeline output (regenerable) — see workspace/data/README.md
│   │   └── market_data/SHFE/aluminum/{sort_by_contract/,sort_by_date.csv,trading_calendar.csv}
│   └── current/backtest/       ← backtest artifacts land here (logs + metrics)
└── strategy/baseline/          ← editable template — fill in your logic here
```

Two trees for two lifecycles: `data/` is **yours** (persists across reruns); `workspace/` is **derived** (the pipeline rebuilds it). Each tree has a `README.md` explaining the split.

**Try this next:** open `./echolon-hello/strategy/baseline/entry.py`, change a parameter (e.g. the breakout lookback in `strategy_params.py`), and re-run:

```bash
echolon backtest single ./echolon-hello/strategy/baseline/
```

Watch the Sharpe shift.

### Start a real project — `echolon init`

```bash
pip install echolon      # akshare is included by default
echolon init my-zinc-strategy --market SHFE --instrument zinc \
                              --start 2022-01-01 --end 2024-12-31 \
                              --template momentum_breakout
```

Downloads zinc OHLCV via akshare (Sina Finance's free mirror — no registry, no token), runs echolon's standardizer pipeline, derives `main_contract.csv` from akshare's continuous-main series, scaffolds a strategy under `my-zinc-strategy/strategy/baseline/`. Fill in business logic in the existing skeleton — echolon's framework structure (class names, method signatures, imports) is already correct.

### Iterate — `echolon backtest single`

```bash
echolon backtest single my-zinc-strategy/strategy/baseline/
```

Walks up from `strategy/baseline/` to find `.echolon-workspace.json`, recovers `--market`, `--instrument`, `--start`, `--end` automatically, recomputes indicators, runs backtest, prints metrics. No flags required.

For agent / CI consumption:

```bash
echolon backtest single my-zinc-strategy/strategy/baseline/ --json
# {
#   "ok": true,
#   "sharpe": 1.04,
#   "max_drawdown": -0.082,
#   "annual_return": 0.18,
#   "total_trades": 142,
#   ...
# }
```

### Discover what's available

| Command | Shows |
|---|---|
| `echolon` (no args) | the three-command quickstart |
| `echolon --version` | installed echolon version |
| `echolon doctor` | dependency pre-flight (ta-lib, akshare) — run first if anything misbehaves |
| `echolon examples --list` | bundled strategy templates with descriptions |
| `echolon indicators list` | indicator catalog (use `--format json` for agents) |
| `echolon schema BacktestConfig` | dump Pydantic JSON schema (for agents writing config from scratch) |
| `echolon validate <strategy_dir>` | check a strategy directory against echolon's contracts (`--json` for agents) |

## Where echolon is today

v0.1.1 is deliberately narrow. What works end-to-end right now is **SHFE daily futures research**: data ingestion, indicator computation against the 217-indicator catalog, backtesting through Backtrader, Optuna TPE optimization (single + multi-objective), walk-forward analysis with deployment-readiness scoring, KMeans-based robust trial selection, and the agent surface described below.

What's in flight, roughly in order:

- SHFE intraday backtesting (data pipeline supports it; the engine pathway is being stabilized)
- Live deployment to SHFE through MiniQMT — the `deploy` CLI exists from earlier internal builds; a clean public release is being written
- Crypto perpetuals (the CCXT adapter is scaffolded but neither backtest nor live is on the near-term roadmap)
- CME futures and equities (architectural slot exists; no implementation yet)

If your work is SHFE futures research with an LLM in the loop, you can use this today. If you need crypto, US markets, or live trading, you're early — open an issue if you want to drive a particular slice and we'll talk about timing.

## What runs on echolon

Echolon is the research engine inside [Qorka](https://dolphinquant.com), [DolphinQuant](https://dolphinquant.com)'s AI-native strategy generation product. Qorka drives the iterative loop on top of echolon — design → code → backtest → analyze → evaluate → refine — and the strategies that survive that loop are deployed live on SHFE. You can see them running in real time on the [DolphinQuant portfolio dashboard](https://dolphinquant.com); Qorka itself is in private beta with a public waitlist on the same site.

Two implications for you:

- **Echolon is exercised by real money on real markets daily.** The error codes, the validators, the contract conventions — they're the way they are because something in production failed in that exact way once. We don't get to ship sloppy.
- **Echolon is fully usable on its own.** If you're here to do your own research, the open-source engine is the whole product, not a stripped demo. The Qorka-side work (paradigm orchestration, mode-decision policy, strategy registry) lives in our private monorepo on top — replaceable by anyone with the engine in hand.

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

## Bring your own data

If you already have raw SHFE XLS files (downloaded from shfe.com.cn) in a directory, run `SHFEFileDayExtractor` directly instead of using akshare. If you have data in another format (broker CSV, tushare pull, custom database), three files must end up under `{workspace}/workspace/data/market_data/SHFE/{instrument}/`:

| File | Schema |
|---|---|
| `sort_by_contract/{contract}.csv` | `contract, date, prev_close, prev_settlement, open, high, low, close, settlement, price_change, settlement_change, volume, turnover, open_interest` |
| `sort_by_date.csv` | Same columns, all rows concatenated and sorted by date. |
| `trading_calendar.csv` | `date, is_trading_day` (boolean). |

Plus under `{workspace}/data/SHFE/{instrument_code}/` (note the SHORT code, e.g. `al` not `aluminum`):

| File | Schema |
|---|---|
| `main_contract.csv` | `date, main_contract` where `main_contract` is the contract code with `.SF` suffix (e.g. `al2401.SF`). One row per change-of-main-contract date. |

Echolon does **not** auto-derive `main_contract.csv` from raw OHLCV — it's a USER input encoding your roll convention (volume / OI / DTE rules). For SHFE via akshare, `echolon init` derives it for you; otherwise produce it yourself and drop it in place.

## Strategy ideas — no LLM required

If you don't want to set up an LLM agent and want to learn by reading, echolon ships three template strategies under `echolon/native/templates/`. Each is a complete, working reference you can study or fork.

- **`minimal`** — the smallest possible strategy. Empty stubs returning hold-forever outputs. Best for understanding the framework's class shape and method contracts before adding any logic.
- **`momentum_breakout`** — 20-bar Donchian breakout entry, ATR-trailing exit. The "hello world" of trend-following. Good template for any strategy whose entry is a price-vs-rolling-window comparison.
- **`rsi_mean_reversion`** — RSI(14) entry below 30 (LONG) / above 70 (SHORT) with time exit. Good template for any oscillator-based reversal strategy.

To copy one into your workspace and iterate:

```bash
echolon examples copy momentum_breakout my-strategy/strategy/baseline/
echolon backtest single my-strategy/strategy/baseline/
```

Or pass `--template <name>` to `echolon init` / `echolon hello` to start from a richer baseline than `minimal`.

## Installation troubleshooting

`pip install echolon` works out of the box on:
- Linux x86_64 (manylinux2014)
- macOS x86_64 + arm64 (M1/M2/M3)
- Windows x86_64
- Python 3.11–3.12

For these, all dependencies (including ta-lib) ship as prebuilt wheels — no compiler needed.

For other platforms (Linux ARM64, Alpine/musl, FreeBSD, Python 3.13+), the only dep that may need source-building is **ta-lib's C library**. Install per platform:

```bash
# Debian / Ubuntu (incl. Raspberry Pi):
sudo apt install ta-lib0 ta-lib-dev
pip install --force-reinstall TA-Lib

# macOS (Homebrew):
brew install ta-lib
pip install --force-reinstall TA-Lib

# From source (any platform):
# https://ta-lib.org/install.html
```

After installing, run `echolon doctor` to confirm everything is wired:

```
$ echolon doctor
  ✓ ta-lib              talib import works (version 0.6.7)
  ✓ akshare             not installed (optional — only needed for `echolon init` data download)
  ✓ backtrader          available
  ✓ optuna              available
```

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

v0.1.1, beta, 2026. Active development. Built and maintained by [DolphinQuant](https://dolphinquant.com) — the same team running Qorka on SHFE. Issues and pull requests welcome at [github.com/dolphinquant/echolon](https://github.com/dolphinquant/echolon).
