"""Verify all public modules are importable."""


def test_import_core():
    from echolon.quant_engine.core.base.base_strategy import BaseStrategy
    from echolon.quant_engine.core.base.base_component import BaseComponent
    from echolon.quant_engine.core.interfaces.trading_interfaces import (
        ITradingEngine,
        IMarketData,
        IPortfolio,
        IOrderManager,
    )
    assert BaseStrategy is not None
    assert BaseComponent is not None
    assert ITradingEngine is not None


def test_import_market_adapters():
    from echolon.quant_engine.market_adapters.shfe.shfe_adapter import SHFEAdapter
    from echolon.quant_engine.market_adapters.crypto.crypto_adapter import CryptoAdapter
    assert SHFEAdapter is not None
    assert CryptoAdapter is not None


def test_import_backtest():
    from echolon.quant_engine.backtest.engine.backtrader_engine import BacktraderEngine
    from echolon.quant_engine.backtest.optimization.optuna_study import OptunaOptimizer
    from echolon.quant_engine.engine_factory import EngineFactory
    assert BacktraderEngine is not None
    assert OptunaOptimizer is not None
    assert EngineFactory is not None


def test_import_data_pipeline():
    from echolon.data_pipeline import extractors, transformers, loaders
    assert extractors is not None


def test_import_indicators():
    from echolon.indicators import calculators
    assert calculators is not None


def test_import_config():
    from echolon.config import quant_engine
    assert quant_engine is not None


def test_import_deploy():
    from echolon.quant_engine.deploy import platforms
    assert platforms is not None
