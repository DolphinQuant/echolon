# Backtest & Live Architecture Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize `echolon/backtest/` and `echolon/live/` into a symmetric, navigable layout. Promote cross-cutting services (`EngineFactory`, `atomic_state`) to top-level primitives. Group related files into subpackages (`backtest/metrics/`, `live/slot/`, `live/io/`, `live/orchestrator/`). Extract the duplicated orchestration boilerplate between `live/runner.py` and `live/portfolio_runner.py` into `AbstractLiveOrchestrator`.

**Architecture:**
- `echolon/engine/` (new top-level) holds the shared `EngineFactory`. Both `backtest/` and `live/` depend on `engine/`; neither reaches into the other.
- `echolon/_internal/` absorbs `state_writer.py` as `atomic_state.py` since it's used by both `live/` and `strategy/`.
- `backtest/metrics/` groups analyzers, mfe_mae, portfolio_metrics, reporting, stats.
- `live/slot/` groups trading_slot, capital_slot, slot_aware_portfolio, risk_overlay.
- `live/io/` groups data_logger and kpi_aggregator (renamed from dashboard).
- `live/orchestrator/` holds `base.py` (AbstractLiveOrchestrator) + `single.py` (was runner.py) + `portfolio.py` (was portfolio_runner.py).
- `live/platforms/ccxt/` deleted (dead stubs).

**Strict constraint:** Behaviour-preserving refactor only. No bug fixes, no API changes, no "while I'm at it" improvements. Every existing test must keep passing. Import-path updates in test files are the only permitted test edits.

**Tech Stack:** Python 3.11+, `git mv` for history preservation, existing pytest suite.

---

## Final File Layout (endpoint)

```
echolon/
├── _internal/
│   ├── atomic_state.py                   # was live/state_writer.py
│   ├── json_utils.py                     (unchanged)
│   └── structured_logging.py             (unchanged)
├── engine/                               # NEW top-level shared subpackage
│   ├── __init__.py
│   └── factory.py                        # was backtest/engine_factory.py
├── backtest/
│   ├── __init__.py, cli.py, schemas.py, runner.py, portfolio_runner.py, logging_utils.py
│   ├── engine/                           # backtest-specific execution layer (unchanged)
│   └── metrics/                          # NEW
│       ├── __init__.py
│       ├── analyzers.py                  # was backtest/analyzers.py
│       ├── mfe_mae.py                    # was backtest/mfe_mae.py
│       ├── portfolio_metrics.py          # was backtest/portfolio_metrics.py
│       ├── reporting.py                  # was backtest/reporting.py
│       └── stats.py                      # was backtest/utils/stats.py
│       (backtest/utils/ removed)
└── live/
    ├── __init__.py, cli.py, config/
    ├── orchestrator/                     # NEW
    │   ├── __init__.py
    │   ├── base.py                       # NEW — AbstractLiveOrchestrator
    │   ├── single.py                     # was live/runner.py
    │   └── portfolio.py                  # was live/portfolio_runner.py
    ├── slot/                             # NEW
    │   ├── __init__.py
    │   ├── trading_slot.py
    │   ├── capital_slot.py
    │   ├── slot_aware_portfolio.py
    │   └── risk_overlay.py               # was live/portfolio_risk.py
    ├── io/                               # NEW
    │   ├── __init__.py
    │   ├── data_logger.py
    │   └── kpi_aggregator.py             # was live/dashboard.py
    └── platforms/
        └── miniqmt/                      (unchanged — qmt_client.py, qmt_engine.py, xtdc_client.py)
        (live/platforms/ccxt/ removed)
```

---

## Execution Rules

1. **One phase per commit.** Each phase lands tests-green independently so bisection and review stay sane.
2. **Use `git mv`** for every relocation so history is preserved.
3. **Never rewrite content during a move.** Only imports inside the moved file may change (to reflect the new locations of its dependencies).
4. **Run the full test suite before committing every phase.** If any test fails, fix imports — do not change behaviour.
5. **Every phase keeps lazy imports lazy.** Do not switch a lazy import to top-level just because "it would look cleaner."
6. **qorka impact:** qorka imports `echolon.backtest.*`, `echolon.live.*`, `echolon.backtest.engine_factory` at minimum. After each phase, list the changed public paths in the commit message so the qorka adapter PR is trivial to follow.

---

## Phase 0: Baseline

- [ ] **Step 0.1:** Capture the clean-tree test baseline.

Run:
```bash
pytest -x --tb=short 2>&1 | tee /tmp/baseline.log
tail -5 /tmp/baseline.log
```
Expected last line: `NN passed in X.XXs` with zero failures. If anything is already red, stop and resolve *before* refactoring.

- [ ] **Step 0.2:** Create the refactor branch.

```bash
git checkout -b refactor/backtest-live-architecture
```

- [ ] **Step 0.3:** Confirm no uncommitted working-tree changes.

```bash
git status --short
```
Expected: empty output.

---

## Phase 1: Move `state_writer.py` → `_internal/atomic_state.py`

**Files:**
- Move: `echolon/live/state_writer.py` → `echolon/_internal/atomic_state.py`
- Update imports in: `echolon/live/portfolio_runner.py`, `echolon/strategy/state_manager.py`, `tests/live/test_state_writer.py`

- [ ] **Step 1.1: Move the file.**

```bash
git mv echolon/live/state_writer.py echolon/_internal/atomic_state.py
```

- [ ] **Step 1.2: Update all import sites.**

```bash
# Find callers
grep -rln "from echolon.live.state_writer" echolon tests
grep -rln "from echolon.live import state_writer" echolon tests
```

For each file listed, rewrite:
- `from echolon.live.state_writer import X` → `from echolon._internal.atomic_state import X`
- `from echolon.live import state_writer` → `from echolon._internal import atomic_state`
- `state_writer.X` → `atomic_state.X`

Known call sites from pre-refactor grep: `echolon/live/portfolio_runner.py`, `echolon/strategy/state_manager.py`, `tests/live/test_state_writer.py`.

- [ ] **Step 1.3: If a test file path itself moved (doesn't apply here), also `git mv` it.** No test file moves in this phase.

- [ ] **Step 1.4: Run tests.**

```bash
pytest -x --tb=short
```
Expected: all green. If a test fails with ImportError, re-check the grep output above for any site you missed.

- [ ] **Step 1.5: Commit.**

```bash
git add -A
git commit -m "refactor(live): move state_writer.py to _internal/atomic_state.py

Shared with strategy/state_manager.py — it's not live-specific.
No behaviour change."
```

---

## Phase 2: Delete `live/platforms/ccxt/` stubs

**Files:**
- Delete: `echolon/live/platforms/ccxt/` (directory)

- [ ] **Step 2.1: Confirm stubs are truly dead.**

```bash
# Anyone importing ccxt_client or ccxt_engine?
grep -rn "ccxt_client\|ccxt_engine" echolon tests
```
Expected: zero hits outside `echolon/live/platforms/ccxt/` itself. If anything else shows, stop and reassess.

- [ ] **Step 2.2: Remove the directory.**

```bash
git rm -r echolon/live/platforms/ccxt
```

- [ ] **Step 2.3: Run tests.**

```bash
pytest -x --tb=short
```
Expected: all green.

- [ ] **Step 2.4: Commit.**

```bash
git commit -m "chore(live): remove ccxt/ stub platform

Dead placeholder files, never imported. Remove to reduce open-source
reader confusion about which platforms are supported."
```

---

## Phase 3: Create `echolon/engine/` top-level subpackage

**Files:**
- Move: `echolon/backtest/engine_factory.py` → `echolon/engine/factory.py`
- Create: `echolon/engine/__init__.py`
- Update imports in: `echolon/backtest/__init__.py`, `echolon/backtest/runner.py`, `echolon/backtest/portfolio_runner.py`, `echolon/backtest/cli.py`, `echolon/backtest/wfa/runner.py`, `echolon/backtest/engine/backtest_runner.py`, `echolon/live/runner.py`, `echolon/live/trading_slot.py`, `echolon/live/cli.py`, `echolon/native/cli/run.py`, `tests/**`

- [ ] **Step 3.1: Create the new subpackage.**

```bash
mkdir -p echolon/engine
touch echolon/engine/__init__.py
```

- [ ] **Step 3.2: Move the factory file.**

```bash
git mv echolon/backtest/engine_factory.py echolon/engine/factory.py
```

- [ ] **Step 3.3: Convert the eager `BacktraderEngine` import inside `factory.py` to lazy.**

Inside `echolon/engine/factory.py`, find this top-level import block:

```python
from echolon.backtest.engine.backtrader_engine import BacktraderEngine
```

Remove it (delete the whole line). Then inside `create_backtest_engine(...)`, move the import to function-body scope:

```python
def create_backtest_engine(cls, ctx, ...):
    from echolon.backtest.engine.backtrader_engine import BacktraderEngine   # lazy
    ...
    return BacktraderEngine(...)
```

This is the same pattern already used for `QMTEngine` in `create_deploy_engine`. The rationale is that `echolon/engine/` must not have a static dependency on `echolon/backtest/` — that dependency direction reverses the shared/specialized layering.

Verify the hook imports in `factory.py` are also lazy or reside inside the factory methods. If they are top-level imports of `echolon.backtest.engine.hooks.*`, move them into the methods too.

- [ ] **Step 3.4: Add backward-compat shim at the old location — NO.**

Strict constraint: no back-compat shims. Every import site must be updated in the same phase.

- [ ] **Step 3.5: Rewrite all import sites.**

```bash
grep -rln "from echolon.backtest.engine_factory" echolon tests
grep -rln "from echolon.backtest import engine_factory" echolon tests
```

For each file: rewrite
- `from echolon.backtest.engine_factory import EngineFactory` → `from echolon.engine.factory import EngineFactory`
- `from echolon.backtest import engine_factory` → `from echolon.engine import factory as engine_factory`
- `echolon.backtest.engine_factory` (strings in tests/docs) → `echolon.engine.factory`

- [ ] **Step 3.6: Remove `EngineFactory` from `echolon/backtest/__init__.py`.**

In `echolon/backtest/__init__.py`, delete the `EngineFactory` entry from `_LAZY_ATTRS` and from `__all__`. Callers that previously did `from echolon.backtest import EngineFactory` must now `from echolon.engine.factory import EngineFactory`.

Grep to make sure no caller relies on the old re-export:
```bash
grep -rn "from echolon.backtest import.*EngineFactory\|echolon.backtest.EngineFactory" echolon tests
```

- [ ] **Step 3.7: Run tests.**

```bash
pytest -x --tb=short
```
Expected: all green. Most likely failure mode: a missed import site. Re-run the greps in 3.5 and 3.6 until empty.

- [ ] **Step 3.8: Commit.**

```bash
git add -A
git commit -m "refactor(engine): promote EngineFactory to top-level echolon.engine

Shared by echolon.backtest (create_backtest_engine) and echolon.live
(create_deploy_engine). Previously in backtest/, which forced live/ to
import from backtest/engine_factory — wrong dependency direction.

BacktraderEngine import moved to lazy (method-scope) to match the
existing QMTEngine lazy import. echolon.engine has no static
dependency on either consumer subpackage.

No behaviour change."
```

---

## Phase 4: Create `backtest/metrics/` subpackage

**Files:**
- Move: `echolon/backtest/analyzers.py` → `echolon/backtest/metrics/analyzers.py`
- Move: `echolon/backtest/mfe_mae.py` → `echolon/backtest/metrics/mfe_mae.py`
- Move: `echolon/backtest/portfolio_metrics.py` → `echolon/backtest/metrics/portfolio_metrics.py`
- Move: `echolon/backtest/reporting.py` → `echolon/backtest/metrics/reporting.py`
- Move: `echolon/backtest/utils/stats.py` → `echolon/backtest/metrics/stats.py`
- Remove: `echolon/backtest/utils/` (directory, after stats.py moved)
- Create: `echolon/backtest/metrics/__init__.py`

- [ ] **Step 4.1: Create the subpackage directory + `__init__.py`.**

```bash
mkdir -p echolon/backtest/metrics
touch echolon/backtest/metrics/__init__.py
```

- [ ] **Step 4.2: Move the five files.**

```bash
git mv echolon/backtest/analyzers.py echolon/backtest/metrics/analyzers.py
git mv echolon/backtest/mfe_mae.py echolon/backtest/metrics/mfe_mae.py
git mv echolon/backtest/portfolio_metrics.py echolon/backtest/metrics/portfolio_metrics.py
git mv echolon/backtest/reporting.py echolon/backtest/metrics/reporting.py
git mv echolon/backtest/utils/stats.py echolon/backtest/metrics/stats.py
```

- [ ] **Step 4.3: Remove the emptied `utils/` directory.**

```bash
# Verify utils/ contains only __init__.py + __pycache__
ls echolon/backtest/utils/
git rm -r echolon/backtest/utils
```

- [ ] **Step 4.4: Rewrite imports.**

```bash
grep -rln "from echolon.backtest.analyzers\|from echolon.backtest.mfe_mae\|from echolon.backtest.portfolio_metrics\|from echolon.backtest.reporting\|from echolon.backtest.utils.stats\|from echolon.backtest.utils import stats" echolon tests
```

For each file, rewrite:
- `from echolon.backtest.analyzers import X` → `from echolon.backtest.metrics.analyzers import X`
- (…same pattern for the other four files)
- `from echolon.backtest.utils.stats` → `from echolon.backtest.metrics.stats`
- `from echolon.backtest.utils import stats` → `from echolon.backtest.metrics import stats`

- [ ] **Step 4.5: Run tests.**

```bash
pytest -x --tb=short
```
Expected: all green.

- [ ] **Step 4.6: Commit.**

```bash
git commit -m "refactor(backtest): group metrics + reporting into metrics/ subpackage

Moves analyzers.py, mfe_mae.py, portfolio_metrics.py, reporting.py,
utils/stats.py under echolon/backtest/metrics/. Deletes the empty
utils/ directory.

No behaviour change."
```

---

## Phase 5: Create `live/slot/` subpackage

**Files:**
- Move: `echolon/live/trading_slot.py` → `echolon/live/slot/trading_slot.py`
- Move: `echolon/live/capital_slot.py` → `echolon/live/slot/capital_slot.py`
- Move: `echolon/live/slot_aware_portfolio.py` → `echolon/live/slot/slot_aware_portfolio.py`
- Move + rename: `echolon/live/portfolio_risk.py` → `echolon/live/slot/risk_overlay.py`
- Create: `echolon/live/slot/__init__.py`

- [ ] **Step 5.1: Create the subpackage directory.**

```bash
mkdir -p echolon/live/slot
touch echolon/live/slot/__init__.py
```

- [ ] **Step 5.2: Move/rename the four files.**

```bash
git mv echolon/live/trading_slot.py echolon/live/slot/trading_slot.py
git mv echolon/live/capital_slot.py echolon/live/slot/capital_slot.py
git mv echolon/live/slot_aware_portfolio.py echolon/live/slot/slot_aware_portfolio.py
git mv echolon/live/portfolio_risk.py echolon/live/slot/risk_overlay.py
```

- [ ] **Step 5.3: Update intra-slot imports.**

Inside the four moved files, the existing imports like
`from .capital_slot import CapitalSlot` still work (relative imports).
But explicit forms like `from echolon.live.capital_slot import …` need
rewriting to `from echolon.live.slot.capital_slot import …`.

Also in `trading_slot.py`: any reference to `SlotAwarePortfolio` via
`from echolon.live.slot_aware_portfolio import …` must become
`from echolon.live.slot.slot_aware_portfolio import …`.

And in `risk_overlay.py`: anywhere it uses the former file name
`portfolio_risk` (log strings, class name etc.) — **do not rename the
class `PortfolioRiskOverlay`**, only the module path. Class name stays.

- [ ] **Step 5.4: Rewrite all external import sites.**

```bash
grep -rln "from echolon.live.trading_slot\|from echolon.live.capital_slot\|from echolon.live.slot_aware_portfolio\|from echolon.live.portfolio_risk\|from echolon.live import trading_slot\|from echolon.live import capital_slot\|from echolon.live import slot_aware_portfolio\|from echolon.live import portfolio_risk" echolon tests
```

For each file: rewrite the module prefix from `echolon.live.<name>` to `echolon.live.slot.<name>`. For the renamed file: `echolon.live.portfolio_risk` → `echolon.live.slot.risk_overlay` (and adjust any `from … import PortfolioRiskOverlay` — class name unchanged).

- [ ] **Step 5.5: Run tests.**

```bash
pytest -x --tb=short
```
Expected: all green.

- [ ] **Step 5.6: Commit.**

```bash
git commit -m "refactor(live): group slot-domain files into live/slot/ subpackage

Moves trading_slot.py, capital_slot.py, slot_aware_portfolio.py
into echolon/live/slot/. Renames portfolio_risk.py to
risk_overlay.py (module rename only — PortfolioRiskOverlay class
name preserved).

No behaviour change."
```

---

## Phase 6: Create `live/io/` subpackage

**Files:**
- Move: `echolon/live/data_logger.py` → `echolon/live/io/data_logger.py`
- Move + rename: `echolon/live/dashboard.py` → `echolon/live/io/kpi_aggregator.py`
- Create: `echolon/live/io/__init__.py`

- [ ] **Step 6.1: Create the subpackage.**

```bash
mkdir -p echolon/live/io
touch echolon/live/io/__init__.py
```

- [ ] **Step 6.2: Move the files.**

```bash
git mv echolon/live/data_logger.py echolon/live/io/data_logger.py
git mv echolon/live/dashboard.py echolon/live/io/kpi_aggregator.py
```

- [ ] **Step 6.3: Preserve the public function names.**

Open `echolon/live/io/kpi_aggregator.py`. The existing public functions
(`generate_dashboard_data`, `aggregate_portfolio`, `load_equity_curve`,
`save_portfolio_dashboard`) **must keep their names** — only the module
path changes. No function-level renames in this phase.

- [ ] **Step 6.4: Rewrite all import sites.**

```bash
grep -rln "from echolon.live.data_logger\|from echolon.live.dashboard\|from echolon.live import data_logger\|from echolon.live import dashboard" echolon tests
```

For each file: rewrite
- `from echolon.live.data_logger` → `from echolon.live.io.data_logger`
- `from echolon.live.dashboard` → `from echolon.live.io.kpi_aggregator`
- `from echolon.live import dashboard` → `from echolon.live.io import kpi_aggregator as dashboard`
  (alias preserves call sites like `dashboard.generate_dashboard_data(...)` without forcing a third change.)

- [ ] **Step 6.5: Also update the public re-export in `echolon/live/__init__.py` if it references `dashboard`.**

Read `echolon/live/__init__.py` and check for any re-export of dashboard functions. Update the module path; keep the public names unchanged.

- [ ] **Step 6.6: Run tests.**

```bash
pytest -x --tb=short
```

- [ ] **Step 6.7: Commit.**

```bash
git commit -m "refactor(live): group I/O files into live/io/; rename dashboard.py to kpi_aggregator.py

dashboard.py was misleading — it's a KPI/equity CSV aggregator that
writes JSON, not a UI or web server. Rename clarifies intent for
open-source readers. Function names preserved.

No behaviour change."
```

---

## Phase 7: Create `live/orchestrator/` subpackage (mechanical moves only)

This phase only relocates and renames the two runner files. The shared-base
extraction happens in Phase 8.

**Files:**
- Move + rename: `echolon/live/runner.py` → `echolon/live/orchestrator/single.py`
- Move + rename: `echolon/live/portfolio_runner.py` → `echolon/live/orchestrator/portfolio.py`
- Create: `echolon/live/orchestrator/__init__.py`

- [ ] **Step 7.1: Create the subpackage.**

```bash
mkdir -p echolon/live/orchestrator
touch echolon/live/orchestrator/__init__.py
```

- [ ] **Step 7.2: Move the files.**

```bash
git mv echolon/live/runner.py echolon/live/orchestrator/single.py
git mv echolon/live/portfolio_runner.py echolon/live/orchestrator/portfolio.py
```

- [ ] **Step 7.3: Preserve class names — do NOT rename them.**

`TradingRunner` and `PortfolioTradingRunner` stay as-is. The point of
this phase is only to park the files under `orchestrator/` so Phase 8
has a clean place to drop `base.py`.

- [ ] **Step 7.4: Rewrite all import sites.**

```bash
grep -rln "from echolon.live.runner\|from echolon.live.portfolio_runner\|from echolon.live import runner\|from echolon.live import portfolio_runner" echolon tests
```

For each file: rewrite
- `from echolon.live.runner import TradingRunner` → `from echolon.live.orchestrator.single import TradingRunner`
- `from echolon.live.portfolio_runner import PortfolioTradingRunner` → `from echolon.live.orchestrator.portfolio import PortfolioTradingRunner`

Include `echolon/live/cli.py`, `echolon/live/__init__.py`, `echolon/native/cli/`, and any test files.

- [ ] **Step 7.5: Run tests.**

```bash
pytest -x --tb=short
```

- [ ] **Step 7.6: Commit.**

```bash
git commit -m "refactor(live): move runners into orchestrator/ subpackage

Relocates runner.py -> orchestrator/single.py, portfolio_runner.py ->
orchestrator/portfolio.py. Class names (TradingRunner,
PortfolioTradingRunner) preserved.

Mechanical moves only. Extracting the shared base class is the next
phase."
```

---

## Phase 8: Extract `AbstractLiveOrchestrator`

This is the only non-mechanical phase. It eliminates the ~30% orchestration
boilerplate duplicated between `orchestrator/single.py` and
`orchestrator/portfolio.py`. The strict-refactor rule applies: end-to-end
behaviour must be byte-identical (same log lines, same file writes, same
scheduling timestamps).

**Files:**
- Create: `echolon/live/orchestrator/base.py`
- Modify: `echolon/live/orchestrator/single.py` (subclass the base)
- Modify: `echolon/live/orchestrator/portfolio.py` (subclass the base)
- Test: existing live-runner tests must pass unchanged. If no live-runner test exists (likely true — they rely on live infra), add characterization tests first.

### Step 8.1: Identify the duplicated surface.

- [ ] **Step 8.1.1: Enumerate the shared methods.**

Open both files side-by-side and list every method whose signature and
behaviour are identical or near-identical. Per the earlier Explore-agent
analysis, the candidates are:

- `_signal_handler(self, signum, frame)` — signal registration and graceful-shutdown flag
- `_schedule_daily_trading(self)` — APScheduler setup
- `_market_open_job(self)` / `_market_close_job(self)` — lifecycle markers
- `stop(self)` — shutdown
- State-file/heartbeat initialisation at `__init__` scope
- Deploy-logger init via `config.logging_config`

Record the exact line ranges in both files as you enumerate. Keep this
list in a scratch buffer — the base class must have the UNION of these
methods with EXACT existing behaviour.

- [ ] **Step 8.1.2: Identify the differences.**

Each subclass must own:
- The per-cycle body: `run_single_cycle(self)` — single-slot engine
  execute vs multi-slot loop over `TradingSlot.execute_bar(...)`.
- State-file paths (single vs per-slot-per-state vs portfolio aggregate).
- `__init__` signature (one `DeployConfig` vs one `PortfolioDeployConfig`).

### Step 8.2: Characterization tests (only add if no equivalent test exists).

- [ ] **Step 8.2.1: Check for existing coverage.**

```bash
grep -rln "TradingRunner\|PortfolioTradingRunner" tests
```

If tests already cover `run()` / `stop()` / signal-handling, skip to 8.3.
If not, write characterisation tests that capture current behaviour
**without** any behavioural assertion beyond "doesn't raise; produces
expected log line set." Put them in `tests/live/test_orchestrator_characterization.py`.

- [ ] **Step 8.2.2: Write the characterisation test.**

```python
# tests/live/test_orchestrator_characterization.py
"""Lock the observable surface of both orchestrators before extracting
the shared base. These tests must pass both BEFORE and AFTER Phase 8.

We do NOT test trading behaviour — only orchestration lifecycle so the
base-class extraction is verified safe."""
import signal
from unittest.mock import patch, MagicMock

from echolon.live.orchestrator.single import TradingRunner
from echolon.live.orchestrator.portfolio import PortfolioTradingRunner


def test_single_orchestrator_signal_handler_sets_stop_flag(tmp_path):
    """_signal_handler(SIGTERM) must flip self._stop_requested to True."""
    with patch("echolon.live.orchestrator.single.MiniQMTClient"):
        runner = _build_minimal_single_runner(tmp_path)
    runner._signal_handler(signal.SIGTERM, None)
    assert runner._stop_requested is True


def test_portfolio_orchestrator_signal_handler_sets_stop_flag(tmp_path):
    """Same contract as single — both runners must behave identically."""
    with patch("echolon.live.orchestrator.portfolio.MiniQMTClient"):
        runner = _build_minimal_portfolio_runner(tmp_path)
    runner._signal_handler(signal.SIGTERM, None)
    assert runner._stop_requested is True


def _build_minimal_single_runner(tmp_path):
    """Construct a TradingRunner with just enough mocks to exercise the
    shared methods. Fill in with real config fixtures already used elsewhere."""
    # See tests/live/conftest.py for existing deploy-config fixtures;
    # reuse rather than fabricating config dicts here.
    ...


def _build_minimal_portfolio_runner(tmp_path):
    ...
```

Complete `_build_minimal_single_runner` and `_build_minimal_portfolio_runner`
with the same fixture pattern already used in `tests/live/`. If there is
genuinely no live-test scaffolding and wiring mocks is extensive, write a
narrower test that only exercises `_signal_handler` as a pure method.

- [ ] **Step 8.2.3: Run the tests — they must pass before extraction.**

```bash
pytest tests/live/test_orchestrator_characterization.py -v
```
Expected: PASS.

### Step 8.3: Extract the base class.

- [ ] **Step 8.3.1: Create `echolon/live/orchestrator/base.py`.**

```python
# echolon/live/orchestrator/base.py
"""Shared lifecycle scaffolding for live orchestrators.

AbstractLiveOrchestrator holds the code that TradingRunner and
PortfolioTradingRunner had in common: signal handling, APScheduler
setup, market-open/close job wiring, and graceful shutdown flagging.
Subclasses implement the cycle-body methods (run_single_cycle,
market_open/close hooks) with their own domain logic.

This class is NOT a behavioural change — it is a mechanical extraction
of previously-duplicated methods. The pre-extraction behaviour of
TradingRunner and PortfolioTradingRunner must be preserved byte-for-byte.
"""
from __future__ import annotations

import abc
import logging
import signal
from typing import Any, Optional


class AbstractLiveOrchestrator(abc.ABC):
    """Base class for live orchestrators.

    Subclasses must implement:
      * run_single_cycle(self) — one trading-cycle body
      * _init_engine(self) / _init_strategy(self) — subclass-specific wiring

    Subclasses inherit (unchanged from the pre-refactor behaviour):
      * _signal_handler, _install_signal_handlers
      * _schedule_daily_trading
      * _market_open_job, _market_close_job
      * stop
    """

    logger: logging.Logger
    _stop_requested: bool

    def __init__(self) -> None:
        self._stop_requested = False

    # -- signal handling ----------------------------------------------------
    def _install_signal_handlers(self) -> None:
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum: int, frame: Any) -> None:
        self.logger.info("Received signal %s, requesting stop", signum)
        self._stop_requested = True

    # -- APScheduler wiring -------------------------------------------------
    def _schedule_daily_trading(self) -> None:
        # COPY verbatim from the pre-extraction TradingRunner._schedule_daily_trading.
        # The two runners had identical bodies — see the Explore-agent report
        # captured in the refactor plan. Do not rewrite the scheduling logic.
        raise NotImplementedError("Fill by copying the shared body from the prior runner.")

    def _market_open_job(self) -> None:
        raise NotImplementedError("Fill by copying.")

    def _market_close_job(self) -> None:
        raise NotImplementedError("Fill by copying.")

    # -- lifecycle ----------------------------------------------------------
    def stop(self) -> None:
        raise NotImplementedError("Fill by copying.")

    # -- subclass contract --------------------------------------------------
    @abc.abstractmethod
    def run_single_cycle(self) -> None:
        ...
```

Actually fill the `_schedule_daily_trading`, `_market_open_job`,
`_market_close_job`, and `stop` method bodies by **copying verbatim**
from whichever of `single.py` / `portfolio.py` you elect as the source
of truth for each method. Do not rewrite. Do not merge branches. If the
two runners' bodies differ in one line, flag it and copy the version
that matches the **single** runner — then in 8.3.3 confirm the diff was
actually a cosmetic difference (log-message string, variable name), not
a behavioural one.

- [ ] **Step 8.3.2: Convert `TradingRunner` to subclass.**

In `echolon/live/orchestrator/single.py`:

1. `from echolon.live.orchestrator.base import AbstractLiveOrchestrator`
2. `class TradingRunner(AbstractLiveOrchestrator):` (replace `class TradingRunner:`)
3. In `__init__`, call `super().__init__()` *first*.
4. **Delete** the method definitions for `_signal_handler`,
   `_install_signal_handlers`, `_schedule_daily_trading`,
   `_market_open_job`, `_market_close_job`, `stop` — they now come from
   the base. Keep `run_single_cycle` (the body differs per subclass).

- [ ] **Step 8.3.3: Convert `PortfolioTradingRunner` to subclass.**

In `echolon/live/orchestrator/portfolio.py`:

Same steps as 8.3.2. If you spot a method you elected to keep in the
subclass because it **genuinely** differs from the single-runner version,
leave it — but add a one-line comment explaining why. Do not call
`super().<method>()` to "blend" — either the base owns the method or
the subclass does.

- [ ] **Step 8.3.4: Run the characterisation tests.**

```bash
pytest tests/live/test_orchestrator_characterization.py -v
```
Expected: PASS, with no new failures.

- [ ] **Step 8.3.5: Run the full suite.**

```bash
pytest -x --tb=short
```
Expected: all green.

- [ ] **Step 8.3.6: Commit.**

```bash
git commit -m "refactor(live): extract AbstractLiveOrchestrator base class

Moves duplicated orchestration boilerplate (signal handling, APScheduler
setup, market-open/close jobs, graceful shutdown) out of TradingRunner
and PortfolioTradingRunner into live/orchestrator/base.py. Both runners
now inherit from AbstractLiveOrchestrator.

Strict refactor only: method bodies copied verbatim from the
pre-extraction runners. Subclass-specific behaviour (per-cycle body,
engine/strategy wiring, state-file paths) stays in the subclasses.

Characterisation tests in tests/live/test_orchestrator_characterization.py
lock the signal-handler contract before and after."
```

---

## Phase 9: Final verification & qorka compatibility note

- [ ] **Step 9.1: Run full suite one last time from a clean state.**

```bash
git status --short   # expect empty
pytest --tb=short 2>&1 | tee /tmp/post-refactor.log
tail -5 /tmp/post-refactor.log
```
Expected: same pass count as Phase 0 baseline.

- [ ] **Step 9.2: Diff the pass count.**

```bash
grep -E "^[0-9]+ passed" /tmp/baseline.log
grep -E "^[0-9]+ passed" /tmp/post-refactor.log
```
Both numbers must be equal. If the post-refactor count is lower, a
test either failed silently (unlikely with `-x`) or was deselected
because its import path changed — audit.

- [ ] **Step 9.3: Produce the qorka-compat changelog.**

Create `docs/MIGRATION_NOTES.md` (or append to an existing one) summarising
the new public import paths that qorka needs to follow:

```markdown
## Refactor 2026-04-21 — backtest/live architecture

Callers (e.g. qorka) must update the following imports:

| Old path                                         | New path                                            |
|--------------------------------------------------|-----------------------------------------------------|
| `echolon.backtest.engine_factory.EngineFactory`  | `echolon.engine.factory.EngineFactory`              |
| `echolon.backtest.analyzers.*`                   | `echolon.backtest.metrics.analyzers.*`              |
| `echolon.backtest.mfe_mae.*`                     | `echolon.backtest.metrics.mfe_mae.*`                |
| `echolon.backtest.portfolio_metrics.*`           | `echolon.backtest.metrics.portfolio_metrics.*`      |
| `echolon.backtest.reporting.*`                   | `echolon.backtest.metrics.reporting.*`              |
| `echolon.backtest.utils.stats.*`                 | `echolon.backtest.metrics.stats.*`                  |
| `echolon.live.state_writer.*`                    | `echolon._internal.atomic_state.*`                  |
| `echolon.live.trading_slot.TradingSlot`          | `echolon.live.slot.trading_slot.TradingSlot`        |
| `echolon.live.capital_slot.CapitalSlot`          | `echolon.live.slot.capital_slot.CapitalSlot`        |
| `echolon.live.slot_aware_portfolio.*`            | `echolon.live.slot.slot_aware_portfolio.*`          |
| `echolon.live.portfolio_risk.PortfolioRiskOverlay` | `echolon.live.slot.risk_overlay.PortfolioRiskOverlay` |
| `echolon.live.data_logger.*`                     | `echolon.live.io.data_logger.*`                     |
| `echolon.live.dashboard.*`                       | `echolon.live.io.kpi_aggregator.*`                  |
| `echolon.live.runner.TradingRunner`              | `echolon.live.orchestrator.single.TradingRunner`    |
| `echolon.live.portfolio_runner.PortfolioTradingRunner` | `echolon.live.orchestrator.portfolio.PortfolioTradingRunner` |
```

- [ ] **Step 9.4: Commit the migration notes.**

```bash
git add docs/MIGRATION_NOTES.md
git commit -m "docs: migration notes for 2026-04-21 backtest/live refactor"
```

- [ ] **Step 9.5: Open the PR.**

```bash
gh pr create --title "refactor(backtest,live): symmetric architecture" --body "<summary from plan + test-pass confirmation>"
```

---

## Self-Review

Before handing off, verify:

1. **Dependency direction** — `echolon.engine` has zero static imports of
   `echolon.backtest` or `echolon.live`. Both concrete engines are lazy.
   ```bash
   grep -E "^from echolon\.(backtest|live)" echolon/engine/*.py
   ```
   Expected: empty output (the `BacktraderEngine` and `QMTEngine` imports
   should live inside the factory methods, not at module top).

2. **No back-compat shims snuck in.** Grep for the old module paths inside
   echolon itself — they should not appear except in `docs/MIGRATION_NOTES.md`.
   ```bash
   grep -rn "echolon.backtest.engine_factory\|echolon.live.state_writer\|echolon.live.dashboard" echolon tests | grep -v MIGRATION_NOTES
   ```
   Expected: empty.

3. **Public `__init__.py` files are up to date.** `echolon/__init__.py`,
   `echolon/backtest/__init__.py`, `echolon/live/__init__.py` should
   reference only the new paths in their lazy-loader tables.

4. **AbstractLiveOrchestrator does not add behaviour.** Diff each shared
   method's body against the pre-extraction version:
   ```bash
   git log --follow -p echolon/live/orchestrator/base.py
   ```
   Inspect that every new line is a verbatim copy, not a rewrite.

5. **ccxt/ is truly gone.** `find echolon -name "ccxt*"` returns nothing.

6. **Commit count.** You should have ~9 commits on the branch:
   Phase 1 through Phase 8, plus the migration notes commit. If you
   squashed any phase into another, note which and why in the PR body.
