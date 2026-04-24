# Platform Architecture

## Three-Layer Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    PLATFORM LAYER                               │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ Backtrader Platform    │    MiniQMT Platform               ││
│  │ • BacktraderTradingEngine  • QMTTradingEngine              ││
│  │ • Platform-specific adapters and implementations           ││
│  └─────────────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────────┤
│             PLATFORM-AGNOSTIC STRATEGY LAYER                    │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │    Strategy Components (Pure Trading Logic)                ││
│  │  • entry.py  • exit.py  • risk.py  • sizer.py             ││
│  │  • strategy.py (main coordinator)                          ││
│  └─────────────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────────┤
│                  ABSTRACTION LAYER                              │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │           Core Interfaces & Base Classes                   ││
│  │  • ITradingEngine  • BaseStrategy  • BaseComponent         ││
│  │  • IMarketData     • IPortfolio    • IOrderManager         ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

## Key Principles

1. **Platform Independence**: Strategy components use only abstract interfaces
2. **Component Specialization**: Each component handles one aspect (entry, exit, risk, sizing)
3. **No Error Handling**: All errors propagate explicitly (no try-except)
4. **Configurable Parameters**: All thresholds loaded from parameters
5. **Standardized Output**: All components return BaseModel instances

## File Organization

Strategy files live in any directory on disk and are loaded by echolon via
`StrategyLoader(strategy_dir).load_module("<name>")`. Host apps choose the
directory location; no fixed filesystem path.

**Qorka convention** (where the coding agent writes):

```
workspace/current/code/
├── entry.py              # Entry signal generation
├── exit.py               # Exit decision logic
├── risk.py               # Risk management
├── sizer.py              # Position sizing
├── strategy.py           # Main coordinator (strategy_main class)
├── strategy_params.py    # Parameter definitions
├── component.py          # Strategy-local helpers (preflight requires presence)
└── strategy_indicator_list.json  # Flat-dict indicator configuration
```

**Required files** (per `echolon/strategy/preflight.py::REQUIRED_FILES`):
`entry.py`, `exit.py`, `risk.py`, `sizer.py`, `component.py`,
`strategy_params.py`, `strategy_indicator_list.json`.

**Required class exports** (per `echolon/strategy/loader.py::_REQUIRED_CLASSES`):

| File | Class name |
|---|---|
| `entry.py` | `entry_rule` |
| `exit.py` | `exit_rule` |
| `risk.py` | `risk_manager` |
| `sizer.py` | `position_sizer` |

`strategy.py`'s class must be named `strategy_main` (loaded via
`StrategyLoader.load_function("strategy", "strategy_main")` — loader.py:13).

## Component Flow

```
┌────────────────────────────────────────────────────────────────┐
│  BaseStrategy._execute_bar()                                   │
│  (override target — NOT on_bar(), which is a Template Method   │
│   orchestrating hook lifecycle; see echolon/strategy/base.py)  │
└──────────────────────────┬─────────────────────────────────────┘
                           │
                           ▼
                ┌──────────────────────┐
                │ risk_manager         │
                │   .can_trade()       │──► RiskOutput
                └──────────┬───────────┘
                           │
     ┌─────────────────────┴─────────────────────┐
     │        has_position()?                    │
     ▼                                           ▼
┌─────────────────────────┐          ┌───────────────────────────┐
│ Flat + trading_allowed: │          │ In position:              │
│   entry_rule            │          │   exit_rule               │
│     .generate_signal()  │── ESO ──►│     .should_exit()        │── XSO
│   if signal != HOLD:    │          │   if should_exit:         │
│     position_sizer      │          │     self.exit(intent)     │
│       .calculate_size() │── SO ──► └───────────────────────────┘
│   if size > 0:          │
│     self.entry(...)     │
└─────────────────────────┘
  ESO = EntrySignalOutput
  SO  = SizerOutput
  XSO = ExitSignalOutput
```

**Key invariants:**

- `_execute_bar()` is the override target — never `on_bar()`. See
  `echolon/strategy/base.py:934` for the Template Method docstring: *"Do NOT
  override this method. Override _execute_bar() instead."*
- Risk check always runs first; `trading_allowed=False` blocks new entries
  but does NOT block exits on existing positions (exit logic still evaluates
  when in position — circuit breakers are the exception; see STRATEGY.md).
- Position-state branches: entry + sizer path fires only when **flat**; exit
  path fires only when **in position**. Exit never runs "after" entry in the
  same bar — they're mutually exclusive per-bar outcomes.
- Always guard order submission with `has_pending_orders()` — see
  STRATEGY.md for the full pattern (Backtrader orders execute at next bar's
  open; without this guard, consecutive bars produce massive over-sized
  positions).

## Documentation Hierarchy

| Source | Purpose |
|--------|---------|
| **Skills** (`/.claude/skills/`) | Patterns, interfaces, examples |
| **Business Logic** (`/workspace/current/strategy/`) | Trading logic, parameters - AUTHORITATIVE |

**Business logic examples in Skills are for ILLUSTRATION only. Agents must source actual logic from `/workspace/current/strategy/`.**
