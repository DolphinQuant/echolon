"""
CCXT Platform Integration
=========================

Cryptocurrency exchange integration via CCXT library.

Components:
- ccxt_engine.py: CCXTEngine implementing ITradingEngine
- ccxt_client.py: CCXT library wrapper

CCXT supports 100+ exchanges:
- Binance (Futures)
- Bybit
- OKX
- Kraken
- And many more

CCXTEngine provides:
- CCXTMarketData: Load data from exchange API
- CCXTPortfolio: Position and balance from exchange
- CCXTOrderManager: Order submission via CCXT
- CCXTLogger: Trading log

Features:
- Unified API across exchanges
- Perpetual futures support
- Real-time data streaming
- Order management

Configuration:
    {
        "execution": {
            "platform": "ccxt",
            "exchange": "binance"
        }
    }

Note: This is a skeleton for future implementation.
Priority is SHFE production, then crypto expansion.
"""

from .ccxt_engine import CCXTEngine
from .ccxt_client import CCXTClient

__all__ = ['CCXTEngine', 'CCXTClient']
