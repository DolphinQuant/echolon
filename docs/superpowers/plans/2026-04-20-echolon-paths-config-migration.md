# Echolon Paths / Config Migration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate import-time cwd binding and module-level path globals in the `echolon` library so it behaves like a well-behaved PyPI package; thread a `PathsConfig` through the ~35 consumer modules; adapt the deep consumer `qorka` to compose its `PathsConfig` at its own entry points.

**Architecture:** Introduce a single `PathsConfig` Pydantic model owning every directory/file path the library touches. Callers construct it once (from their own project root, from `platformdirs`, or from explicit paths) and inject it through the public entry points (`run_data_pipeline`, `run_live_data_update`, `run_backtest`, `run_indicator_calculation`, etc.). Echolon internals stop importing `echolon.config.settings` constants at module scope; they accept paths via config objects or positional parameters. The existing `BacktestConfig` path fields (`market_data_dir`, `indicator_dir`, `strategy_dir`, `results_dir`) stay; `PathsConfig` is the *source* those fields are populated from. `qorka` keeps its own `config/settings.py` (with its correct `PROJECT_ROOT = Path(__file__).parent.parent.absolute()`) and builds a `PathsConfig` at every entry point that calls into echolon.

**Tech Stack:** Python 3.11+, Pydantic v2, pathlib, pytest. `platformdirs` is an optional dependency used only by a convenience factory; the library must not require it.

---

## File Structure

**New files in `echolon/`:**
- `echolon/config/paths_config.py` — the `PathsConfig` Pydantic model + `from_project_root()` and `from_platformdirs()` factory helpers.
- `tests/config/test_paths_config.py` — unit tests for the model and factories.
- `tests/config/test_no_cwd_at_import.py` — regression test asserting `echolon.config.settings` does not read cwd at import time.

**Modified echolon files (one commit per group):**

| Group | Files |
|---|---|
| Settings surface | `echolon/config/settings.py`, `echolon/config/__init__.py` |
| Data entry points | `echolon/data/backtest_data.py`, `echolon/data/live_data.py`, `echolon/data/__init__.py` |
| Data loaders | `echolon/data/loaders/ohlcv_loader.py`, `echolon/data/loaders/calendar_loader.py`, `echolon/data/loaders/session_availability_loader.py`, `echolon/data/loaders/backtest_data_loader.py` |
| Data extractors | `echolon/data/extractors/shfe/file_day_extractor.py`, `echolon/data/extractors/shfe/api_minute_extractor.py`, `echolon/data/extractors/binance/perpetual_extractor.py` |
| Markets layer | `echolon/markets/shfe/contract_rules.py`, `echolon/config/markets/factory.py` |
| Indicators | `echolon/indicators/optimization/interday_regime_optimizer.py` |
| Backtest engine | `echolon/backtest/engine/backtest_runner.py`, `echolon/backtest/engine/backtrader_strategy.py`, `echolon/backtest/mfe_mae.py`, `echolon/backtest/wfa/runner.py`, `echolon/backtest/optimization/optuna_study.py`, `echolon/backtest/optimization/select_best_trial.py` |
| Strategy | `echolon/strategy/generators/strategy_params_generator.py`, `echolon/strategy/utils/strategy_log.py` |
| Live | `echolon/live/runner.py`, `echolon/live/portfolio_runner.py`, `echolon/live/trading_slot.py`, `echolon/live/config/deploy_config.py` |

**Modified qorka files:**

| Group | Files |
|---|---|
| Composition layer | `qorka/config/quant_engine.py` (add `build_paths_config`), `qorka/config/settings.py` (no changes — qorka continues to own its project-relative paths) |
| Orchestrators | `qorka/orchestrator/strategy_dev.py`, `qorka/orchestrator/run_backtest.py` |
| Scripts | `qorka/scripts/run_portfolio_backtest.py`, `qorka/scripts/debug_backtest.py` |
| Libs | `qorka/lib/file_operation.py`, `qorka/lib/concatenate_strategy.py`, `qorka/modules/backtest_metrics/utils/backtest_loader.py` |

**Deleted:**
- From `echolon/config/settings.py`: `load_dotenv()`, `get_workspace_dir`, `get_data_dir`, `get_dataset_dir`, `DOLPHIN_*` env var references, eventually every module-level path constant.

---

## Task 0: Pre-flight audit

**Files:**
- Read-only: confirm the current import surface before touching anything.

- [ ] **Step 1: Enumerate current external consumers**

Run: `rg -n "from echolon\.config\.settings import" echolon/ qorka/ | sort -u`

Save the output to `/tmp/settings-consumers.txt` for reference. This is the set of imports the plan must eliminate by the end of Phase 4.

- [ ] **Step 2: Confirm `DOLPHIN_*` / getter functions have zero callers**

Run: `rg -n "get_workspace_dir|get_data_dir|get_dataset_dir|DOLPHIN_WORKSPACE|DOLPHIN_DATA_DIR|DOLPHIN_DATASET_DIR" echolon/ qorka/`

Expected: only the definitions in `echolon/config/settings.py`. If anything else surfaces, flag it and update Task 1 to preserve that caller.

- [ ] **Step 3: Confirm the `BacktestConfig` path fields already exist**

Run: `rg -n "market_data_dir|indicator_dir|strategy_dir|results_dir" echolon/config/backtest_config.py`

Expected: all four fields are declared on `BacktestConfig`. If any are missing, add them in Task 2 before proceeding.

- [ ] **Step 4: Commit a no-op marker for the migration branch**

```bash
git checkout -b paths-config-migration
git commit --allow-empty -m "chore: start paths-config migration"
```

---

## Task 1: Remove dead code — `load_dotenv()`, `DOLPHIN_*` getters

**Files:**
- Modify: `echolon/config/settings.py`
- Test: `tests/config/test_no_cwd_at_import.py` (new)

- [ ] **Step 1: Write the failing regression test for cwd-at-import**

Create `tests/config/test_no_cwd_at_import.py`:

```python
"""Regression: echolon.config.settings must not read cwd at import time."""
import importlib
import os
import sys
from pathlib import Path


def test_settings_import_does_not_bind_cwd(tmp_path, monkeypatch):
    """Importing echolon.config.settings from a different cwd must not
    leak that cwd into module constants."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ECHOLON_PROJECT_ROOT", raising=False)

    # Force a fresh import
    for name in list(sys.modules):
        if name.startswith("echolon.config.settings"):
            del sys.modules[name]

    mod = importlib.import_module("echolon.config.settings")

    # After Task 4 the constants are gone entirely; for now assert that
    # no module-level attribute equals tmp_path-rooted cwd.
    assert not hasattr(mod, "PROJECT_ROOT") or Path(mod.PROJECT_ROOT) != tmp_path.resolve()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/config/test_no_cwd_at_import.py -v`

Expected: FAIL — `mod.PROJECT_ROOT == tmp_path.resolve()`.

- [ ] **Step 3: Remove `load_dotenv()` and the three getter functions from `settings.py`**

Edit `echolon/config/settings.py`:

```python
# DELETE these lines at the top:
from dotenv import load_dotenv

load_dotenv()

# DELETE the "Convenience getter functions" block (currently lines 43–61):
# get_workspace_dir / get_data_dir / get_dataset_dir
```

Resulting header:

```python
"""Engine configuration — data paths and directory structure.

This file contains ONLY path configuration needed by the engine.
API keys and LLM configuration belong in the CLI product, not here.

All paths are derived from ECHOLON_PROJECT_ROOT (defaults to cwd) —
callers should prefer constructing an echolon.config.paths_config.PathsConfig
rather than importing these constants directly.
"""

import os
from pathlib import Path

# =============================================================================
# Project Root
# =============================================================================
PROJECT_ROOT = Path(os.getenv("ECHOLON_PROJECT_ROOT", Path.cwd())).absolute()
```

- [ ] **Step 4: Regression-test still fails but for the right reason**

Run: `pytest tests/config/test_no_cwd_at_import.py -v`

Expected: still FAIL — we haven't killed `PROJECT_ROOT` yet. The getter removal only unblocked the file. Update the test docstring to note this is checked again in Task 4.

- [ ] **Step 5: Run the full test suite to confirm no dead-code regression**

Run: `pytest -q`

Expected: green. If any failure surfaces, it means a caller of `get_workspace_dir` / `get_data_dir` / `get_dataset_dir` was missed in the pre-flight audit — restore the offender and update Task 0 before proceeding.

- [ ] **Step 6: Commit**

```bash
git add echolon/config/settings.py tests/config/test_no_cwd_at_import.py
git commit -m "chore(config): drop load_dotenv + unused DOLPHIN_* getters from settings"
```

---

## Task 2: Introduce `PathsConfig` Pydantic model

**Files:**
- Create: `echolon/config/paths_config.py`
- Test: `tests/config/test_paths_config.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/config/test_paths_config.py`:

```python
"""PathsConfig — single source of truth for library-owned directory layout."""
from pathlib import Path

import pytest
from pydantic import ValidationError

from echolon.config.paths_config import PathsConfig


def test_from_project_root_conventional_layout(tmp_path: Path):
    paths = PathsConfig.from_project_root(tmp_path)
    assert paths.project_root == tmp_path.resolve()
    assert paths.session_dir == tmp_path / "session"
    assert paths.workspace_dir == tmp_path / "workspace"
    assert paths.output_dir == tmp_path / "output"
    assert paths.raw_data_dir == tmp_path / "data"
    assert paths.market_data_dir == tmp_path / "workspace" / "data" / "market_data"
    assert paths.indicators_research_dir == tmp_path / "workspace" / "data" / "indicators" / "research"
    assert paths.indicators_backtest_dir == tmp_path / "workspace" / "data" / "indicators" / "backtest"
    assert paths.current_dir == tmp_path / "workspace" / "current"
    assert paths.strategy_code_dir == tmp_path / "workspace" / "current" / "code"
    assert paths.backtest_results_dir == tmp_path / "workspace" / "current" / "backtest"
    assert paths.best_params_file == tmp_path / "workspace" / "current" / "code" / "selected_robust_trial.json"
    assert paths.deploy_config_file == tmp_path / "session" / "deploy_config.json"


def test_explicit_override(tmp_path: Path):
    paths = PathsConfig.from_project_root(
        tmp_path,
        market_data_dir=tmp_path / "custom_md",
    )
    assert paths.market_data_dir == tmp_path / "custom_md"
    # Non-overridden stays conventional
    assert paths.raw_data_dir == tmp_path / "data"


def test_all_paths_are_absolute(tmp_path: Path):
    paths = PathsConfig.from_project_root(tmp_path)
    for name, value in paths.model_dump().items():
        if isinstance(value, Path):
            assert value.is_absolute(), f"{name} must be absolute; got {value}"


def test_string_accepted_at_construction(tmp_path: Path):
    paths = PathsConfig.from_project_root(str(tmp_path))
    assert isinstance(paths.project_root, Path)


def test_missing_required_root_raises():
    with pytest.raises(ValidationError):
        PathsConfig()  # project_root is required


def test_platformdirs_factory(monkeypatch):
    """Optional factory for pip-installed usage; uses platformdirs if available."""
    pytest.importorskip("platformdirs")
    paths = PathsConfig.from_platformdirs("echolon-test")
    assert paths.project_root.is_absolute()
    assert "echolon-test" in str(paths.project_root)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/config/test_paths_config.py -v`

Expected: FAIL — `ModuleNotFoundError: echolon.config.paths_config`.

- [ ] **Step 3: Implement `PathsConfig`**

Create `echolon/config/paths_config.py`:

```python
"""PathsConfig — single source of truth for echolon directory layout.

A PyPI library must not bind its filesystem layout to the user's cwd at
import time. Callers construct one PathsConfig and inject it at the
library's public entry points (``run_data_pipeline``, ``run_backtest``,
``run_indicator_calculation``, etc.).

Typical usage from a host project (e.g. qorka)::

    from echolon.config.paths_config import PathsConfig
    paths = PathsConfig.from_project_root(Path(__file__).parent.parent)
    run_data_pipeline(ctx, paths=paths)

Or, for pip-installed end-users without a project layout::

    paths = PathsConfig.from_platformdirs("echolon")
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class PathsConfig(BaseModel):
    """Every directory and file path echolon writes to or reads from."""

    model_config = {"arbitrary_types_allowed": True}

    # Root
    project_root: Path

    # Top-level
    session_dir: Path
    workspace_dir: Path
    output_dir: Path
    raw_data_dir: Path

    # Workspace → data
    market_data_dir: Path
    indicators_research_dir: Path
    indicators_backtest_dir: Path

    # Workspace → current iteration
    current_dir: Path
    strategy_code_dir: Path            # workspace/current/code
    backtest_results_dir: Path         # workspace/current/backtest
    current_analysis_dir: Path         # workspace/current/analysis

    # Specific files
    best_params_file: Path             # strategy_code_dir / "selected_robust_trial.json"
    deploy_config_file: Path           # session_dir / "deploy_config.json"

    @field_validator("*", mode="before")
    @classmethod
    def _coerce_to_path(cls, v: Any) -> Any:
        return Path(v) if isinstance(v, str) else v

    @model_validator(mode="after")
    def _absolutise(self) -> "PathsConfig":
        for name in self.model_fields:
            value = getattr(self, name)
            if isinstance(value, Path) and not value.is_absolute():
                object.__setattr__(self, name, value.resolve())
        return self

    @classmethod
    def from_project_root(cls, project_root: Path | str, **overrides: Path | str) -> "PathsConfig":
        """Build from conventional <root>/{session,workspace,output,data} layout.

        Any field can be overridden by keyword (e.g. ``market_data_dir=...``).
        """
        root = Path(project_root).absolute()
        workspace = root / "workspace"
        indicators = workspace / "data" / "indicators"
        current = workspace / "current"
        strategy_code = current / "code"

        defaults: dict[str, Path] = {
            "project_root": root,
            "session_dir": root / "session",
            "workspace_dir": workspace,
            "output_dir": root / "output",
            "raw_data_dir": root / "data",
            "market_data_dir": workspace / "data" / "market_data",
            "indicators_research_dir": indicators / "research",
            "indicators_backtest_dir": indicators / "backtest",
            "current_dir": current,
            "strategy_code_dir": strategy_code,
            "backtest_results_dir": current / "backtest",
            "current_analysis_dir": current / "analysis",
            "best_params_file": strategy_code / "selected_robust_trial.json",
            "deploy_config_file": root / "session" / "deploy_config.json",
        }
        defaults.update({k: Path(v) for k, v in overrides.items()})
        return cls(**defaults)

    @classmethod
    def from_platformdirs(cls, app_name: str = "echolon") -> "PathsConfig":
        """Build using platformdirs (XDG on Linux, %APPDATA% on Windows).

        Requires the optional dependency ``platformdirs``. Suitable for
        pip-installed end-users without a project layout of their own.
        """
        from platformdirs import user_data_dir
        return cls.from_project_root(user_data_dir(app_name, ensure_exists=False))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/config/test_paths_config.py -v`

Expected: all tests pass (the platformdirs test will skip if the dep isn't installed; install it into the test env if it isn't already).

- [ ] **Step 5: Export `PathsConfig` from `echolon.config`**

Edit `echolon/config/__init__.py` (create if absent):

```python
from echolon.config.paths_config import PathsConfig
from echolon.config.indicator_config import IndicatorConfig

__all__ = ["PathsConfig", "IndicatorConfig"]
```

(If the file already has exports, *append* these rather than overwrite.)

- [ ] **Step 6: Commit**

```bash
git add echolon/config/paths_config.py tests/config/test_paths_config.py echolon/config/__init__.py
git commit -m "feat(config): add PathsConfig — single source for library-owned paths"
```

---

## Task 3: Thread `PathsConfig` through the data layer

**Files:**
- Modify: `echolon/data/backtest_data.py`, `echolon/data/live_data.py`, `echolon/data/__init__.py`
- Modify: `echolon/data/loaders/*.py` (4 files)
- Test: `tests/data/test_paths_injection.py` (new)

- [ ] **Step 1: Write the failing injection tests**

Create `tests/data/test_paths_injection.py`:

```python
"""Data-layer entry points must accept an injected PathsConfig."""
import inspect

from echolon.config.paths_config import PathsConfig
from echolon.data.backtest_data import run_data_pipeline
from echolon.data.live_data import run_live_data_update


def test_run_data_pipeline_accepts_paths():
    sig = inspect.signature(run_data_pipeline)
    assert "paths" in sig.parameters
    assert sig.parameters["paths"].annotation.__args__[0] is PathsConfig or \
           sig.parameters["paths"].annotation is PathsConfig


def test_run_live_data_update_accepts_paths():
    sig = inspect.signature(run_live_data_update)
    assert "paths" in sig.parameters
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/data/test_paths_injection.py -v`

Expected: FAIL — `paths not in parameters`.

- [ ] **Step 3: Add `paths: PathsConfig | None = None` to both entry points**

Edit `echolon/data/backtest_data.py`:

```python
from echolon.config.paths_config import PathsConfig
# ... remove: from echolon.config.settings import MARKET_DATA_DIR, RAW_DATA_DIR

def run_data_pipeline(
    ctx: TradingContext,
    *,
    paths: PathsConfig | None = None,
    input_dir: Optional[str] = None,
    output_dir: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    skip_extraction: bool = False,
    start_contract: Optional[str] = None,
) -> bool:
    """... (existing docstring, plus:)

    Args:
        paths: PathsConfig supplying library-owned directory layout.
               When None the conventional layout rooted at ECHOLON_PROJECT_ROOT
               is used (deprecated fallback — callers SHOULD supply paths).
    ...
    """
    if paths is None:
        from echolon.config.settings import PROJECT_ROOT
        paths = PathsConfig.from_project_root(PROJECT_ROOT)

    market = ctx.market_code
    instrument = ctx.instrument_name
    # ...
    output_path = Path(output_dir) if output_dir else paths.market_data_dir / market / instrument
    # ... update other references from MARKET_DATA_DIR → paths.market_data_dir
    #                                   RAW_DATA_DIR   → paths.raw_data_dir
```

Also update the private helper `_load_source_data(market, instrument, frequency)` to accept `paths: PathsConfig` and read `paths.raw_data_dir` instead of importing `RAW_DATA_DIR`. Update the one caller.

Apply the analogous change to `echolon/data/live_data.py`:

```python
from echolon.config.paths_config import PathsConfig
# remove: from echolon.config.settings import MARKET_DATA_DIR

def run_live_data_update(
    ctx,
    client,
    *,
    paths: PathsConfig | None = None,
    output_dir: Optional[str] = None,
    trading_calendar_path: Optional[str] = None,
    present_date=None,
    skip_calendar: bool = False,
) -> bool:
    if paths is None:
        from echolon.config.settings import PROJECT_ROOT
        paths = PathsConfig.from_project_root(PROJECT_ROOT)
    # ...
    output_path = Path(output_dir) if output_dir else paths.market_data_dir / market / instrument
```

- [ ] **Step 4: Verify injection tests pass**

Run: `pytest tests/data/test_paths_injection.py -v`

Expected: PASS.

- [ ] **Step 5: Migrate the four loaders**

Each loader currently does `from echolon.config.settings import MARKET_DATA_DIR`. Convert them to accept `market_data_dir: Path | None = None` and default-import only inside the function body (deprecated fallback):

Files:
- `echolon/data/loaders/ohlcv_loader.py`
- `echolon/data/loaders/calendar_loader.py`
- `echolon/data/loaders/session_availability_loader.py`
- `echolon/data/loaders/backtest_data_loader.py`

Pattern (apply to each):

```python
# BEFORE
from echolon.config.settings import MARKET_DATA_DIR

def load_ohlcv(market, instrument, *, path=None):
    if path is None:
        path = MARKET_DATA_DIR / market / instrument / "ohlcv.parquet"
    ...

# AFTER
def load_ohlcv(market, instrument, *, path=None, market_data_dir=None):
    if path is None:
        if market_data_dir is None:
            from echolon.config.settings import PROJECT_ROOT
            from echolon.config.paths_config import PathsConfig
            market_data_dir = PathsConfig.from_project_root(PROJECT_ROOT).market_data_dir
        path = market_data_dir / market / instrument / "ohlcv.parquet"
    ...
```

The point is to make the module-level `MARKET_DATA_DIR` import unnecessary while preserving backward compatibility. A lazy local import inside the fallback branch keeps the cost zero for callers who pass explicit paths.

- [ ] **Step 6: Run full `tests/data/` suite**

Run: `pytest tests/data/ -q`

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add echolon/data/backtest_data.py echolon/data/live_data.py \
        echolon/data/loaders/ohlcv_loader.py echolon/data/loaders/calendar_loader.py \
        echolon/data/loaders/session_availability_loader.py echolon/data/loaders/backtest_data_loader.py \
        echolon/data/__init__.py tests/data/test_paths_injection.py
git commit -m "feat(data): accept injected PathsConfig at entry points + loaders"
```

---

## Task 4: Migrate extractors, markets layer, indicators

**Files:**
- Modify: `echolon/data/extractors/shfe/file_day_extractor.py`, `echolon/data/extractors/shfe/api_minute_extractor.py`, `echolon/data/extractors/binance/perpetual_extractor.py`
- Modify: `echolon/markets/shfe/contract_rules.py`, `echolon/config/markets/factory.py`
- Modify: `echolon/indicators/optimization/interday_regime_optimizer.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/data/test_paths_injection.py`:

```python
def test_no_module_level_settings_import_in_extractors():
    """Extractors and the markets layer must not bind settings paths at import time."""
    import ast, pathlib
    forbidden_symbols = {"RAW_DATA_DIR", "MARKET_DATA_DIR", "INDICATOR_DIR",
                         "PROJECT_ROOT", "WORKSPACE_DIR", "OUTPUT_DIR", "SESSION_DIR"}
    base = pathlib.Path(__file__).parent.parent.parent / "echolon"
    offenders = []
    targets = [
        base / "data" / "extractors",
        base / "markets",
        base / "indicators" / "optimization",
    ]
    for root in targets:
        for py in root.rglob("*.py"):
            tree = ast.parse(py.read_text())
            for node in ast.iter_child_nodes(tree):  # top-level only
                if isinstance(node, ast.ImportFrom) and node.module == "echolon.config.settings":
                    leaked = {a.name for a in node.names} & forbidden_symbols
                    if leaked:
                        offenders.append((py.relative_to(base), sorted(leaked)))
    assert not offenders, f"module-level settings imports: {offenders}"
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/data/test_paths_injection.py::test_no_module_level_settings_import_in_extractors -v`

Expected: FAIL — lists the current offenders.

- [ ] **Step 3: Remove module-level settings imports from extractors**

Each extractor currently has `from echolon.config.settings import RAW_DATA_DIR` at top. Delete that line. Any function that needs a default raw-data directory takes a `raw_data_dir: Path | None = None` kwarg; if `None`, lazy-import `PROJECT_ROOT` inside the function and derive via `PathsConfig.from_project_root(PROJECT_ROOT).raw_data_dir`.

Apply to:
- `echolon/data/extractors/shfe/file_day_extractor.py`
- `echolon/data/extractors/shfe/api_minute_extractor.py`
- `echolon/data/extractors/binance/perpetual_extractor.py`

- [ ] **Step 4: Same treatment for markets layer**

- `echolon/markets/shfe/contract_rules.py:32` — `from echolon.config.settings import RAW_DATA_DIR` → move to lazy import or accept `raw_data_dir` parameter (read the file to see which is less invasive; probably a module-level function signature change).
- `echolon/config/markets/factory.py:33` — `from echolon.config.settings import SESSION_DIR, OUTPUT_DIR` → same treatment. These are likely used for session discovery; accept `session_dir: Path | None = None, output_dir: Path | None = None` on the relevant factory methods.

- [ ] **Step 5: Indicator optimizer**

- `echolon/indicators/optimization/interday_regime_optimizer.py:1093` already lazy-imports `MARKET_DATA_DIR`. Convert to take `market_data_dir: Path | None = None` on the `optimize_regime_params` wrapper and thread through. Remove the lazy import.

- [ ] **Step 6: Re-run**

Run: `pytest tests/data/test_paths_injection.py -v && pytest -q tests/`

Expected: all green. If the "no module-level settings import" test still reports offenders, the migration is incomplete — do not commit.

- [ ] **Step 7: Commit**

```bash
git add -u
git commit -m "refactor(data/markets/indicators): drop module-level settings imports, inject paths"
```

---

## Task 5: Migrate backtest + strategy + live layers

**Files:**
- Modify: `echolon/backtest/engine/backtest_runner.py`, `echolon/backtest/engine/backtrader_strategy.py`, `echolon/backtest/mfe_mae.py`
- Modify: `echolon/backtest/wfa/runner.py`, `echolon/backtest/optimization/optuna_study.py`, `echolon/backtest/optimization/select_best_trial.py`
- Modify: `echolon/strategy/generators/strategy_params_generator.py`, `echolon/strategy/utils/strategy_log.py`
- Modify: `echolon/live/runner.py`, `echolon/live/portfolio_runner.py`, `echolon/live/trading_slot.py`, `echolon/live/config/deploy_config.py`

- [ ] **Step 1: Extend the regression test to cover these subsystems**

Append to `tests/data/test_paths_injection.py`:

```python
def test_no_module_level_settings_import_in_backtest_strategy_live():
    import ast, pathlib
    forbidden_symbols = {"RAW_DATA_DIR", "MARKET_DATA_DIR", "INDICATOR_DIR",
                         "PROJECT_ROOT", "WORKSPACE_DIR", "OUTPUT_DIR", "SESSION_DIR",
                         "PLATFORM_AGNOSTIC_DIR", "BACKTEST_RESULTS_DIR",
                         "STRATEGY_LOG_DIR", "BEST_PARAMS_FILE", "DEPLOY_CONFIG_DIR",
                         "INDICATORS_BACKTEST_DIR", "INDICATORS_RESEARCH_DIR"}
    base = pathlib.Path(__file__).parent.parent.parent / "echolon"
    offenders = []
    for group in ("backtest", "strategy", "live"):
        for py in (base / group).rglob("*.py"):
            tree = ast.parse(py.read_text())
            for node in ast.iter_child_nodes(tree):  # top-level only
                if isinstance(node, ast.ImportFrom) and node.module == "echolon.config.settings":
                    leaked = {a.name for a in node.names} & forbidden_symbols
                    if leaked:
                        offenders.append((py.relative_to(base), sorted(leaked)))
    assert not offenders, f"module-level settings imports: {offenders}"
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/data/test_paths_injection.py::test_no_module_level_settings_import_in_backtest_strategy_live -v`

Expected: FAIL — lists every current offender.

- [ ] **Step 3: Migrate each file**

Apply the same pattern as Task 4: delete module-level `from echolon.config.settings import …`, accept the relevant path(s) as a function/constructor parameter, lazy-import the global fallback only inside the `None` branch. Preserve backward compatibility (no required new parameters) but encourage callers via docstrings.

Order of migration (lowest → highest risk):
1. `echolon/strategy/utils/strategy_log.py` (single `OUTPUT_DIR` import; isolated logger).
2. `echolon/backtest/mfe_mae.py` (both `MARKET_DATA_DIR` and `INDICATOR_DIR` at module top; function-scoped usage).
3. `echolon/backtest/optimization/optuna_study.py` (single `INDICATOR_DIR`).
4. `echolon/backtest/optimization/select_best_trial.py` (single `PLATFORM_AGNOSTIC_DIR`).
5. `echolon/backtest/wfa/runner.py` (two imports: `WORKSPACE_DIR`, `PLATFORM_AGNOSTIC_DIR`).
6. `echolon/strategy/generators/strategy_params_generator.py` (single `WORKSPACE_DIR`).
7. `echolon/backtest/engine/backtest_runner.py` (multiple imports, already uses lazy imports too).
8. `echolon/backtest/engine/backtrader_strategy.py` (lazy imports only — convert to constructor parameter).
9. `echolon/live/*` (lazy imports only — convert to constructor parameter on runners).

For each file, run the project test suite after the change (`pytest -q`) before moving to the next to catch regressions at the point of introduction.

- [ ] **Step 4: Run the full regression test**

Run: `pytest tests/data/test_paths_injection.py -v && pytest -q tests/`

Expected: all green.

- [ ] **Step 5: Commit after each of the nine files (recommended) or one bundled commit**

Preferred:

```bash
# after each file, e.g. strategy_log:
git add echolon/strategy/utils/strategy_log.py
git commit -m "refactor(strategy_log): accept output_dir parameter, drop OUTPUT_DIR import"
# ...repeat for the other eight
```

Single-commit alternative:

```bash
git add -u
git commit -m "refactor(backtest/strategy/live): drop module-level settings imports, inject paths"
```

---

## Task 6: Delete the globals from `echolon/config/settings.py`

**Files:**
- Modify: `echolon/config/settings.py`

- [ ] **Step 1: Re-run the "no module-level settings import" regression tests**

Run: `pytest tests/data/test_paths_injection.py -v`

Expected: both tests PASS — every echolon module now imports only `PROJECT_ROOT` from settings (at most) inside function bodies.

- [ ] **Step 2: Grep for remaining callers**

Run: `rg -n "from echolon\.config\.settings import" echolon/`

Expected: only `PROJECT_ROOT` imports remain, all inside functions (not module-scope). If anything else surfaces, go back to Tasks 3–5.

- [ ] **Step 3: Rewrite `echolon/config/settings.py` to hold only `PROJECT_ROOT`**

```python
"""ECHOLON_PROJECT_ROOT resolver.

This module is deliberately minimal. Library callers should construct
``echolon.config.paths_config.PathsConfig`` explicitly; ``PROJECT_ROOT``
here is the fallback used only when a caller supplies no paths at all.
"""
import os
from pathlib import Path


def get_project_root() -> Path:
    """Lazy resolver for ECHOLON_PROJECT_ROOT (defaults to cwd)."""
    return Path(os.getenv("ECHOLON_PROJECT_ROOT", Path.cwd())).absolute()


# Backwards-compatible module attribute.  Prefer get_project_root().
# This will be removed in a subsequent release once every fallback branch
# in the library is rewritten to call get_project_root() directly.
PROJECT_ROOT = get_project_root()
```

Note: `PROJECT_ROOT` still evaluates at import, but the library no longer *depends* on its value — every caller now has an injection path. The cwd-binding test remains an attribute check for `PROJECT_ROOT`; tighten it by switching the library's internal fallbacks from `from echolon.config.settings import PROJECT_ROOT` to `from echolon.config.settings import get_project_root` and calling it at use-time.

- [ ] **Step 4: Convert the ~9 lazy fallbacks to `get_project_root()`**

For each `if paths is None: from echolon.config.settings import PROJECT_ROOT` branch introduced in Tasks 3–5, change to `from echolon.config.settings import get_project_root; PROJECT_ROOT = get_project_root()`. This makes the fallback honor env-var changes made after import.

- [ ] **Step 5: Tighten the cwd-at-import regression test**

Edit `tests/config/test_no_cwd_at_import.py`:

```python
def test_settings_import_does_not_bind_cwd(tmp_path, monkeypatch):
    """Importing echolon.config.settings must not bake cwd into library behaviour."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ECHOLON_PROJECT_ROOT", raising=False)

    import sys
    for name in list(sys.modules):
        if name.startswith("echolon"):
            del sys.modules[name]

    # Import data layer; it must not blow up and must not pin paths to cwd
    from echolon.data.loaders.ohlcv_loader import load_ohlcv
    from echolon.config.paths_config import PathsConfig

    # Changing cwd after import must still be visible via get_project_root()
    monkeypatch.chdir(tmp_path.parent)
    from echolon.config.settings import get_project_root
    assert get_project_root() == tmp_path.parent.resolve()
```

- [ ] **Step 6: Run full suite**

Run: `pytest -q`

Expected: green.

- [ ] **Step 7: Commit**

```bash
git add -u
git commit -m "refactor(config): shrink settings.py to PROJECT_ROOT + get_project_root()"
```

---

## Task 7: qorka — add `build_paths_config()` factory

**Files:**
- Modify: `qorka/config/quant_engine.py`

- [ ] **Step 1: Write a smoke test on the qorka side**

Create `qorka/tests/config/test_build_paths_config.py`:

```python
"""qorka composes echolon's PathsConfig from its own project-relative layout."""
from pathlib import Path

from echolon.config.paths_config import PathsConfig
from config.quant_engine import build_paths_config


def test_build_paths_config_uses_qorka_project_root():
    paths = build_paths_config()
    assert isinstance(paths, PathsConfig)
    # PROJECT_ROOT is derived from Path(__file__).parent.parent in qorka/config/settings.py;
    # confirm the workspace lives under that root.
    from config.settings import PROJECT_ROOT
    assert paths.project_root == Path(PROJECT_ROOT)
    assert paths.market_data_dir == Path(PROJECT_ROOT) / "workspace" / "data" / "market_data"
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest qorka/tests/config/test_build_paths_config.py -v`

Expected: FAIL — `build_paths_config` not importable.

- [ ] **Step 3: Add the factory**

Edit `qorka/config/quant_engine.py`, after `build_indicator_config`:

```python
from echolon.config.paths_config import PathsConfig as _PathsConfig


def build_paths_config() -> _PathsConfig:
    """Construct echolon PathsConfig from qorka's project-relative layout.

    qorka resolves PROJECT_ROOT at import time via its own
    ``config/settings.py`` (which uses ``Path(__file__).parent.parent``,
    so the root is always the qorka repo checkout — not the user's cwd).
    This factory exposes that layout to echolon.
    """
    return _PathsConfig.from_project_root(PROJECT_ROOT)
```

- [ ] **Step 4: Verify test passes**

Run: `pytest qorka/tests/config/test_build_paths_config.py -v`

Expected: PASS.

- [ ] **Step 5: Commit (in qorka)**

```bash
cd /home/yzj/projects/quantitive_trading/qorka
git add config/quant_engine.py tests/config/test_build_paths_config.py
git commit -m "feat(config): build_paths_config() — expose qorka layout to echolon"
```

---

## Task 8: qorka — inject `PathsConfig` at every entry point

**Files:**
- Modify: `qorka/orchestrator/strategy_dev.py`, `qorka/orchestrator/run_backtest.py`
- Modify: `qorka/scripts/run_portfolio_backtest.py`, `qorka/scripts/debug_backtest.py`
- Modify: `qorka/lib/file_operation.py`, `qorka/lib/concatenate_strategy.py`, `qorka/modules/backtest_metrics/utils/backtest_loader.py`

- [ ] **Step 1: Write the "no echolon settings leak" regression on the qorka side**

Create `qorka/tests/test_no_echolon_settings_leak.py`:

```python
"""qorka must compose echolon PathsConfig rather than leak echolon.config.settings."""
import ast, pathlib


def test_qorka_does_not_import_echolon_settings():
    forbidden = "echolon.config.settings"
    base = pathlib.Path(__file__).parent.parent
    offenders = []
    for py in base.rglob("*.py"):
        # allow under docs/ and .venv/
        rel = py.relative_to(base)
        if rel.parts and rel.parts[0] in {"docs", ".venv", "tests"}:
            continue
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == forbidden:
                offenders.append((str(rel), node.lineno))
    assert not offenders, f"qorka still imports from {forbidden}: {offenders}"
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest qorka/tests/test_no_echolon_settings_leak.py -v`

Expected: FAIL — lists the seven offenders in the file table above.

- [ ] **Step 3: Migrate `qorka/orchestrator/strategy_dev.py`**

Replace the existing `run_data_pipeline(ctx=self.ctx, ...)` call with the paths-injected form:

```python
from config.quant_engine import build_paths_config

# inside _prepare_data:
success = run_data_pipeline(
    ctx=self.ctx,
    paths=build_paths_config(),
    skip_extraction=skip_extraction,
    start_contract=start_contract,
)
```

Remove any `from echolon.config.settings import …` (there are none in this file today, but re-grep after editing).

- [ ] **Step 4: Migrate `qorka/orchestrator/run_backtest.py`**

Replace the two `from echolon.config.settings import INDICATOR_DIR` and `from echolon.config.settings import PLATFORM_AGNOSTIC_DIR` lazy imports with `build_paths_config()`-sourced values:

```python
paths = build_paths_config()
# ... where INDICATOR_DIR was referenced:
indicator_dir = paths.indicators_backtest_dir
# ... where PLATFORM_AGNOSTIC_DIR was referenced:
strategy_code_dir = paths.strategy_code_dir
```

Also update `from config.quant_engine import ..., PLATFORM_AGNOSTIC_DIR, INDICATOR_DIR` (line 65) — those module-level globals in `qorka/config/quant_engine.py` can stay for backwards compatibility, but new code should use `build_paths_config()`.

- [ ] **Step 5: Migrate scripts and libs**

For `qorka/scripts/debug_backtest.py`, `qorka/scripts/run_portfolio_backtest.py`, `qorka/lib/file_operation.py`, `qorka/lib/concatenate_strategy.py`, `qorka/modules/backtest_metrics/utils/backtest_loader.py`:

Replace every `from echolon.config.settings import PLATFORM_AGNOSTIC_DIR` / `INDICATOR_DIR` with:

```python
from config.quant_engine import build_paths_config
_paths = build_paths_config()
PLATFORM_AGNOSTIC_DIR = _paths.strategy_code_dir   # or convert to function, per file's style
INDICATOR_DIR = _paths.indicators_backtest_dir
```

If the file is only using the constant for a single call, prefer inlining `build_paths_config().strategy_code_dir` at the use site rather than creating a module-level rebinding.

- [ ] **Step 6: Verify the regression passes**

Run: `pytest qorka/tests/test_no_echolon_settings_leak.py -v`

Expected: PASS.

- [ ] **Step 7: Run qorka's own test suite**

Run (from qorka root): `pytest -q`

Expected: green. If a script fails at import (e.g. because it used a module-global that was deleted), either reinstate the module-level binding from `build_paths_config()` or fix the caller.

- [ ] **Step 8: Commit**

```bash
cd /home/yzj/projects/quantitive_trading/qorka
git add -u
git commit -m "refactor: inject echolon PathsConfig at entry points, drop settings leak"
```

---

## Task 9: Documentation

**Files:**
- Modify: `echolon/docs/API_REFERENCE.md`, `echolon/docs/CONFIG_REFERENCE.md`, `echolon/docs/QUICK_START.md`
- Modify: `echolon/CHANGELOG.md`

- [ ] **Step 1: Add `PathsConfig` to the Config reference**

Append a section to `echolon/docs/CONFIG_REFERENCE.md`:

```markdown
## PathsConfig

Every directory and file path echolon touches lives on `PathsConfig`.

**Construct from a project root** (conventional layout):

    from echolon.config.paths_config import PathsConfig
    paths = PathsConfig.from_project_root("/path/to/my_project")

**For pip-installed end-users without a project layout:**

    paths = PathsConfig.from_platformdirs("echolon")

**Inject at every public entry point:**

    run_data_pipeline(ctx, paths=paths, ...)
    run_live_data_update(ctx, client, paths=paths, ...)
    run_backtest(ctx, paths=paths, ...)

**Fields:** project_root, session_dir, workspace_dir, output_dir, raw_data_dir,
market_data_dir, indicators_research_dir, indicators_backtest_dir, current_dir,
strategy_code_dir, backtest_results_dir, current_analysis_dir, best_params_file,
deploy_config_file.

**Overrides:** Any field can be overridden at `from_project_root` time:

    paths = PathsConfig.from_project_root(root, market_data_dir=Path("/mnt/bigdisk/md"))
```

- [ ] **Step 2: Update QUICK_START with an end-to-end example**

Append to `echolon/docs/QUICK_START.md`:

```markdown
## End-to-end: a library user with an explicit project root

    from pathlib import Path
    from echolon.config.paths_config import PathsConfig
    from echolon.config.markets.factory import MarketFactory
    from echolon.data import run_data_pipeline

    paths = PathsConfig.from_project_root(Path("/data/echolon-proj"))
    ctx = MarketFactory.build(market="SHFE", instrument="aluminum", frequency="day")
    run_data_pipeline(ctx, paths=paths, skip_extraction=False)
```

- [ ] **Step 3: CHANGELOG entry**

Prepend to the `Unreleased` section of `CHANGELOG.md`:

```markdown
### Config surface alignment (PathsConfig migration)

- New `echolon.config.paths_config.PathsConfig`: single Pydantic model
  holding every library-owned directory and file path. Callers construct
  one (`from_project_root(...)` or `from_platformdirs(...)`) and inject
  it via a new `paths=` parameter on every public entry point
  (`run_data_pipeline`, `run_live_data_update`, `run_backtest`, etc.).
- Library code no longer imports module-level path constants from
  `echolon.config.settings` at top of modules — every consumer has
  moved to config injection (fallback to `PROJECT_ROOT` retained,
  deferred to function bodies).
- Deleted: `load_dotenv()` auto-call, `get_workspace_dir/get_data_dir/
  get_dataset_dir` getters, `DOLPHIN_WORKSPACE/DOLPHIN_DATA_DIR/
  DOLPHIN_DATASET_DIR` env vars. Libraries do not silently consume
  `.env` files; move `load_dotenv()` to your CLI entry point.
- `echolon/config/settings.py` now contains only `PROJECT_ROOT` plus the
  `get_project_root()` lazy resolver.
- **Migration for host projects:** construct a `PathsConfig` at each
  entry point into echolon; see `docs/CONFIG_REFERENCE.md#pathsconfig`.
```

- [ ] **Step 4: Commit**

```bash
cd /home/yzj/projects/quantitive_trading/echolon
git add docs/ CHANGELOG.md
git commit -m "docs(config): document PathsConfig, update QUICK_START and CHANGELOG"
```

---

## Task 10: Final verification

- [ ] **Step 1: Run every suite**

```bash
cd /home/yzj/projects/quantitive_trading/echolon
pytest -q
cd /home/yzj/projects/quantitive_trading/qorka
pytest -q
```

Both must be green.

- [ ] **Step 2: Audit for any remaining bare `echolon.config.settings` imports at module scope**

```bash
cd /home/yzj/projects/quantitive_trading/echolon
rg -n "^from echolon\.config\.settings import" echolon/ tests/
```

Expected: zero hits except inside functions. (The regex anchors `^` to line start.)

- [ ] **Step 3: Audit for cwd-binding at import**

```bash
cd /tmp
ECHOLON_PROJECT_ROOT= python -c "
import os
os.chdir('/tmp')
import echolon
from echolon.config.settings import PROJECT_ROOT
print('PROJECT_ROOT =', PROJECT_ROOT)
# /tmp is fine as a fallback, but the library must not have *used* this value
# to create anything.  Verify by listing /tmp for side-effect directories:
import pathlib
side_effects = {p.name for p in pathlib.Path('/tmp').iterdir()} & \
               {'session', 'workspace', 'output', 'data'}
assert not side_effects, f'library created dirs as a side-effect: {side_effects}'
"
```

Expected: no assertion error. If any of those four dirs appears under `/tmp`, a module-level `.mkdir()` call was missed.

- [ ] **Step 4: Final commit marker**

```bash
cd /home/yzj/projects/quantitive_trading/echolon
git commit --allow-empty -m "chore: paths-config migration complete"
```

---

## Risks & Rollback

- **Risk:** A subsystem's tests pass but a runtime script fails because of a module-level deletion. **Mitigation:** Task 5 recommends committing per file and running `pytest -q` after each; the regression test in Task 4/5 catches top-level imports but not deferred ones. Run the integration scripts in `qorka/scripts/` once per phase.
- **Risk:** `qorka` callers outside the list surface later (e.g. via import * or dynamic import). **Mitigation:** The AST-based regression in Task 8 catches every `ImportFrom`; dynamic imports (`__import__`, `importlib.import_module`) are separate — grep for those too before declaring done.
- **Rollback:** The migration is on branch `paths-config-migration`. Every task is a commit. `git revert <sha>` undoes any one step without affecting the others. `git reset --hard main` on the branch aborts the whole migration.

## Open Questions (resolve before starting)

1. **Do we preserve the `PROJECT_ROOT` fallback indefinitely, or deprecate with a warning?** Recommendation: keep it for one release, emit a `DeprecationWarning` in Task 6 if a fallback path is ever used, delete in the *next* release. This gives qorka time to migrate in staging without a hard break.
2. **Does `PathsConfig.from_platformdirs` need to be in the core, or split into an optional extras package `echolon[platformdirs]`?** Recommendation: keep it in core; `platformdirs` is a tiny pure-Python dep and every real PyPI user will need it.
3. **Should we add `ECHOLON_WORKSPACE` / `ECHOLON_MARKET_DATA_DIR` env-var overrides on `PathsConfig`?** Recommendation: no for this migration. Env-var-driven paths are a host-application concern; `qorka` can read its env, build its own `PROJECT_ROOT`, and call `PathsConfig.from_project_root(PROJECT_ROOT)`.
