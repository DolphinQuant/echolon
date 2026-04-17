# Quick Start

Install Echolon, create a minimal strategy, run your first backtest.

## 1. Install

```bash
pip install echolon
```

## 2. Create a strategy

```bash
echolon init-strategy my_first --template minimal
```

This creates `./my_first/` with 7 files:
- `strategy.py` — strategy coordinator
- `entry.py`, `exit.py`, `risk.py`, `sizer.py` — component files
- `strategy_params.py` — parameter definitions
- `strategy_indicator_list.json` — which indicators to compute
- `README.md` — template notes

## 3. Validate it

```bash
echolon validate my_first/
```

Should print: `✓ Strategy directory is valid.`

## 4. Customize `entry.py`

Open `my_first/entry.py` and replace the HOLD-forever logic with your signal.

## 5. Run backtest

```bash
echolon run my_first/ --instrument cu --start 2020-01-01 --end 2023-12-31
```

## If you hit an error

Every error includes a code like `[VAL-001]`. Look it up in [ERROR_CATALOG.md](ERROR_CATALOG.md) or at `https://echolon.dev/docs/errors/{code}`.

## Next Steps

- Read [COMPONENT_GUIDE.md](COMPONENT_GUIDE.md) to understand each component
- Browse [PATTERNS.md](PATTERNS.md) for canonical strategy shapes
- See [CONFIG_REFERENCE.md](CONFIG_REFERENCE.md) for full configuration options
