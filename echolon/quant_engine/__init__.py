"""
Quant Engine Module
===================

Unified trading engine supporting multiple markets, frequencies, and platforms.

This module consolidates all trading components:
- core/: Interfaces, base classes, and frequency contexts
- strategy/: Platform-agnostic strategy code (single source of truth)
- market_adapters/: Replaceable market-specific adapters (SHFE, crypto, CME)
- backtest/: Backtesting engine and optimization
- deploy/: Live trading engine and platform integrations
- data/: Data loading and indicator calculation

Usage:
    # Create engine using factory
    from modules.quant_engine import EngineFactory, run_backtest

    # Load config and create backtest engine
    config = EngineFactory.load_config('config.json')
    engine = EngineFactory.create_backtest_engine(config)

    # Or run directly
    from modules.quant_engine.run_backtest import run_backtest
    results = run_backtest(config_path='config.json')
"""

