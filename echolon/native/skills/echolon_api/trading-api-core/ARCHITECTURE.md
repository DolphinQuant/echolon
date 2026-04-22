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

```
modules/quant_engine/strategy/platform_agnostic/
├── entry.py              # Entry signal generation
├── exit.py               # Exit decision logic
├── risk.py               # Risk management
├── sizer.py              # Position sizing
├── strategy.py           # Main coordinator (strategy_main class)
├── strategy_params.py    # Parameter definitions
└── strategy_indicator_list.json  # Required indicators
```

## Component Flow

```
┌──────────────┐
│  on_bar()    │  BaseStrategy coordinator
└──────┬───────┘
       │
       ▼
┌──────────────┐     RiskOutput
│ risk_manager │────────────────┐
│  .can_trade()│                │
└──────────────┘                │
       │                        │
       ▼ (if trading_allowed)   │
┌──────────────┐                │
│  entry_rule  │ EntrySignalOutput
│.generate_signal()─────────────┤
└──────────────┘                │
       │                        │
       ▼ (if signal != HOLD)    │
┌──────────────┐                │
│position_sizer│ SizerOutput    │
│.calculate_size()──────────────┤
└──────────────┘                │
       │                        │
       ▼ (submit order)         │
┌──────────────┐                │
│  exit_rule   │ ExitSignalOutput
│ .should_exit()────────────────┘
└──────────────┘
```

## Documentation Hierarchy

| Source | Purpose |
|--------|---------|
| **Skills** (`/.claude/skills/`) | Patterns, interfaces, examples |
| **Business Logic** (`/workspace/current/strategy/`) | Trading logic, parameters - AUTHORITATIVE |

**Business logic examples in Skills are for ILLUSTRATION only. Agents must source actual logic from `/workspace/current/strategy/`.**
