# Changelog

All notable changes to echolon are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/). Pre-1.0 minor and patch
versions may carry breaking changes — they are clearly flagged below.

## 0.1.3 — 2026-05-05

User-facing logging cleanup. ``echolon hello`` and the default
``echolon backtest single`` path no longer flood stdout with per-bar
``[DEBUG] Bar N | START/END`` and ``[DEBUG] Risk | TRADING_ALLOWED``
trace lines. Pass ``--verbose`` (or ``-v``) to restore that trace.

### New

- New ``summary`` run_context (``echolon.backtest.logging_utils``).
  Root INFO so workflow milestones remain visible
  (``[BACKTEST_RUNNER] Complete``, ``[STRATEGY_BRIDGE] Indicators``);
  bar-loop loggers (``backtrader_strategy``, ``strategy.component``,
  contract-aware/session-aware hooks) demoted to WARNING so per-bar
  trace is suppressed. ``echolon hello`` and non-verbose
  ``echolon backtest single`` now use this context by default.

### Fixed

- ``should_log_details`` now correctly gates only ``debug`` and
  ``best_trial`` (was: every non-``optimization`` context). The new
  ``summary`` context returns False, matching user expectation that
  the default invocation prints a one-line Sharpe summary, not 1500
  lines of per-bar trace.
- ``BacktestRunner.run`` no longer silently coerces unknown contexts to
  ``best_trial``. Canonical contexts (``optimization``/``summary``/
  ``debug``/``best_trial``) pass through verbatim; non-canonical
  legacy values (``custom``/``manual``/``backtest``) still fall back to
  ``best_trial`` for back-compat.
- ``echolon.backtest.logging_utils._current_context`` ContextVar default
  changed from ``"debug"`` to ``"summary"``. Test paths and library
  callers that hit the logger without first calling
  ``setup_backtest_logging`` no longer flood stdout.
- ``echolon backtest single --verbose`` help text corrected — previously
  claimed it surfaced a DEBUG-level trace, but the trace was always on
  regardless of the flag. Now the flag actually controls the trace.

## 0.1.2 — 2026-05-04

Second public release. Hardens the dependency-injection contract, trims the
CLI surface, fixes a backlog of path-resolution bugs surfaced by host-app
integration, and ships `llms.txt` directly into scaffolded workspaces.

### Breaking changes

- **`PathsConfig` is now required everywhere.** Every library entry point
  (`run_data_pipeline`, `run_backtest`, `run_best_trial`,
  `run_indicator_calculation`, `WFARunner`, `PortfolioBacktestRunner`, …)
  takes `paths: PathsConfig` as a kwarg-only required parameter. Library
  code no longer falls back to `PathsConfig.from_env()`; the strategy
  bridge raises `CFG-003` if path strategy params aren't injected.
  Construct one `PathsConfig` at startup (via
  `PathsConfig.from_project_root(<root>)` or `from_platformdirs`) and
  thread it through.
- **`echolon run` removed.** Use `echolon backtest single <strategy_dir>` —
  it walks up to the workspace marker and recovers ctx, so no flags are
  required.
- **`echolon init-strategy` back-compat alias removed.** Use `echolon init`.
- **Default workspace layout flattened**: `workspace/strategy/baseline/` +
  `workspace/backtest/` (was `workspace/current/...`). Host apps with
  iteration-loop layouts override via the workspace marker's `paths` field.
- **Legacy strategy imports**: `from ...core.base.X` no longer resolves.
  Run `echolon migrate <strategy_dir>` to rewrite to the current absolute
  paths (`echolon.strategy.X`).
- **`Position` field cleanup**: `entry_price`, `side`, `is_short`,
  `is_flat` removed; only `is_long` survives. Use `position.avg_price`
  for the entry price; check direction via `position.direction`
  (`"LONG"` / `"SHORT"` / `"FLAT"`).
- **Pydantic v2 idioms**: strategy output schemas use
  `model_config = ConfigDict(extra="allow")` instead of the deprecated
  `class Config:` block.

### New

- **`llms.txt` shipped into every workspace.** `echolon init` /
  `echolon hello` drop the agent orientation manual at the workspace
  root, so an LLM agent walking into the project finds it without
  needing the MCP server up.
- **Data pipeline auto-populates `main_contract.csv`.** Step 6 of
  `run_data_pipeline` either copies a curated `main_contract.csv` from
  the raw data tree or derives it via the max-volume rule. Previously a
  separate scaffolding step.

### Fixed

- WFA OOS replay: paths threaded through `BacktestRunner.best_trial`,
  `get_trading_calendar_instance`, `load_indicator_metadata`, and the
  SHFE adapter's `market_data_dir`. Resolves a chain of `CFG-003`
  errors that fired on every per-window backtest.
- Contract-aware broker now probes slot-style indicator dir first and
  falls back to instrument-style
  (`{indicator_dir}/{slot}/by_contract/` or
  `{indicator_dir}/{instrument}/by_contract/`) — supports both
  `echolon backtest single` (slot layout) and host-app iteration-loop
  pipelines (instrument layout).
- SHFE day-data extractor default subdir aligned with the natural
  convention: `{raw_data_dir}/SHFE/day_data/` (was the misleading
  `raw_data/`).
- README runtime-registration table: corrected OpenAI Agents SDK row
  (previous form raised `TypeError`; now uses the required `params`
  dict), added the missing outer-wrapper note for Cursor's `mcpServers`
  config, replaced the vague Codex CLI pointer with the documented
  `codex mcp add` command, replaced the LangChain pointer with a
  copy-pasteable `MultiServerMCPClient` snippet.

### Internal cleanup

- Removed `validation-backup/` skill tree from echolon (relocated to
  qorka — the KEEP/REVERT workflow is qorka-internal, not generic
  backtest infra).
- Renamed test fixture `al_v6_1_migrated/` → `aluminum_baseline/` and
  scrubbed qorka-specific path references from fixture file headers.
- Skill-doc audit pass: removed qorka-internal class names
  (`ExplorationOrchestrator` / `ExploitationOrchestrator`),
  internal-task-tracker references ("Task 6 audit"), and outdated
  migration framing.
- README rewrite (EN + zh-CN): trimmed from ~265 lines to ~104,
  restructured around the two journeys readers actually have (try via
  CLI in 30 seconds; drive from an LLM agent). Native-Chinese tone
  pass to drop translation-shaped phrasings.

## 0.1.1 — 2026-04-18

First public release on PyPI. SHFE daily futures research toolkit for LLM
agents — bundles an MCP server, in-package skills, catalogued error codes,
typed Pydantic configs, working strategy templates, Backtrader-based
backtesting, Optuna TPE optimization (single + multi-objective),
walk-forward analysis with deployment-readiness scoring, and KMeans-based
robust trial selection. Production engine inside
[Qorka](https://dolphinquant.com), DolphinQuant's AI-native strategy
generation product.
