"""
Market Factory - Creates TradingContext from session state.

This is the primary entry point for obtaining market configuration.
It reads session/state.json and returns a fully configured TradingContext.

Usage:
    from config.markets.factory import MarketFactory

    # Create from session state (most common)
    ctx = MarketFactory.from_session()

    # Create with explicit parameters
    ctx = MarketFactory.create(
        market='SHFE',
        instrument='al',
        frequency='intraday',
        bar_size='5m'
    )

    # Use the context
    print(f"Trading {ctx.instrument_name} on {ctx.market_code}")
    print(f"Bars per day: {ctx.bars_per_day}")
"""

import json
from pathlib import Path
from typing import Optional

from config.markets.core.context import TradingContext
from config.markets.core.types import MarketConfig, InstrumentSpec
from config.markets.core.trading_target import TradingTarget, TradingTargetConfigSchema
from config.settings import SESSION_DIR, OUTPUT_DIR


class MarketFactory:
    """
    Factory for creating TradingContext instances.

    Reads session state and creates appropriately configured contexts
    with all market-specific functions and data attached.
    """

    # Cache for loaded market configs
    _market_configs: dict = {}

    @classmethod
    def from_session(cls, session_path: Optional[str] = None) -> TradingContext:
        """
        Create TradingContext from session state file.

        Loading priority:
        1. If OUTPUT_DIR/target.json exists, load it directly (already integrated)
        2. Otherwise, load state.json and trading_target_*.json from SESSION_DIR

        Args:
            session_path: Path to session state JSON. Defaults to session/state.json

        Returns:
            Configured TradingContext

        Raises:
            FileNotFoundError: If session state file doesn't exist
            ValidationError: If required fields are missing or invalid
        """
        # Check if integrated target exists in OUTPUT_DIR
        output_target_path = Path(OUTPUT_DIR) / "target.json"
        if output_target_path.exists():
            # Load from OUTPUT_DIR/target.json (already has integrated target)
            with open(output_target_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            target = TradingTarget.model_validate(data)
        else:
            # Load from session/state.json
            target = TradingTarget.load(session_path)
            # Load and validate trading target config based on frequency
            target.target = cls._load_trading_target_config(target.frequency)

        return cls.create(
            market=target.market,
            instrument=target.instrument_code,
            frequency=target.frequency,
            bar_size=target.bar_size,
            target=target,
        )

    @classmethod
    def _load_trading_target_config(cls, frequency: str) -> Optional[TradingTargetConfigSchema]:
        """
        Load and validate trading target config based on frequency.

        Args:
            frequency: 'intraday' or 'interday'

        Returns:
            Validated TradingTargetConfigSchema or None if file doesn't exist

        Raises:
            ValidationError: If trading target JSON has invalid structure
        """
        if frequency == "intraday":
            target_file = "trading_target_intraday.json"
        else:
            target_file = "trading_target_interday.json"

        target_path = Path(SESSION_DIR) / target_file

        if not target_path.exists():
            return None

        with open(target_path, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)

        # Validate against schema
        return TradingTargetConfigSchema.model_validate(raw_data)

    @classmethod
    def load_target(cls, session_path: Optional[str] = None) -> TradingTarget:
        """
        Load TradingTarget from session state file with trading target config.

        Loading priority:
        1. If OUTPUT_DIR/target.json exists, load it directly (already integrated)
        2. Otherwise, load state.json and trading_target_*.json from SESSION_DIR

        Use this when you need the full target info (including user_request).

        Args:
            session_path: Path to session state JSON. Defaults to session/state.json

        Returns:
            Validated TradingTarget instance with target config
        """
        # Check if integrated target exists in OUTPUT_DIR
        output_target_path = Path(OUTPUT_DIR) / "target.json"
        if output_target_path.exists():
            # Load from OUTPUT_DIR/target.json (already has integrated target)
            with open(output_target_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return TradingTarget.model_validate(data)

        # Load from session/state.json
        target = TradingTarget.load(session_path)
        # Load and validate trading target config based on frequency
        target.target = cls._load_trading_target_config(target.frequency)
        return target

    @classmethod
    def create(
        cls,
        market: str,
        instrument: str,
        frequency: str,
        bar_size: str,
        target: 'TradingTarget' = None,
    ) -> TradingContext:
        """
        Create TradingContext with explicit parameters.

        Args:
            market: Market code ('SHFE', 'CRYPTO')
            instrument: Instrument code ('al', 'btc')
            frequency: 'intraday' or 'interday'
            bar_size: Bar size ('1m', '5m', '15m', '1h', '1d')
            target: Optional TradingTarget with user's trading configuration

        Returns:
            Configured TradingContext

        Raises:
            ValueError: If market or instrument is not supported
        """
        market_upper = market.upper()
        instrument_lower = instrument.lower()

        # Get market config
        market_config = cls._get_market_config(market_upper)
        if market_config is None:
            supported = cls._get_supported_markets()
            raise ValueError(
                f"Unsupported market: '{market}'. Supported: {supported}"
            )

        # Get instrument spec using flexible lookup (supports code or name)
        instrument_spec = cls.get_instrument_flexible(market_upper, instrument_lower)
        if instrument_spec is None:
            supported = list(market_config.instruments.keys())
            raise ValueError(
                f"Unsupported instrument: '{instrument}' for market '{market}'. "
                f"Supported: {supported}"
            )

        # Get encoding functions (bar_size-aware for SHFE aggregated phases)
        encode_fn, decode_fn = cls._get_encoding_functions(market_upper, bar_size)

        return TradingContext(
            market=market_config,
            instrument=instrument_spec,
            frequency=frequency,
            bar_size=bar_size,
            target=target,
            _encode_phase=encode_fn,
            _decode_phase=decode_fn,
        )

    @classmethod
    def _get_market_config(cls, market_code: str) -> Optional[MarketConfig]:
        """Get market configuration, loading if necessary."""
        if market_code not in cls._market_configs:
            cls._load_market(market_code)
        return cls._market_configs.get(market_code)

    @classmethod
    def _load_market(cls, market_code: str) -> None:
        """Load market configuration module."""
        if market_code == 'SHFE':
            from config.markets.shfe.config import CONFIG
            cls._market_configs['SHFE'] = CONFIG
        elif market_code == 'CRYPTO':
            from config.markets.crypto.config import CONFIG
            cls._market_configs['CRYPTO'] = CONFIG
        # Add more markets here as needed

    @classmethod
    def _get_encoding_functions(cls, market_code: str, bar_size: str) -> tuple:
        """
        Get phase encoding/decoding functions for a market.

        Creates bar_size-aware functions that use the correct encoding
        for granular (5m/15m) vs aggregated (30m/1h) phases.

        Args:
            market_code: Market code (e.g., 'SHFE')
            bar_size: Bar size string (e.g., '30m') to determine encoding

        Returns:
            Tuple of (encode_fn, decode_fn) with bar_size baked in
        """
        if market_code == 'SHFE':
            from config.markets.shfe.phases import encode_phase, decode_phase
            # Create bar_size-aware functions
            return (
                lambda phase_str: encode_phase(phase_str, bar_size),
                lambda phase_code: decode_phase(phase_code, bar_size)
            )
        elif market_code == 'CRYPTO':
            # Crypto doesn't have session phases in the same way
            # Return identity functions
            return lambda _: 0, lambda _: 'continuous'

        # Default: no-op functions
        return lambda _: 0, lambda _: 'unknown'

    @classmethod
    def _get_supported_markets(cls) -> list:
        """Get list of supported market codes."""
        return ['SHFE', 'CRYPTO']

    @classmethod
    def get_market_config(cls, market: str) -> Optional[MarketConfig]:
        """
        Get raw market configuration.

        For cases where you need the config without creating a full context.

        Args:
            market: Market code

        Returns:
            MarketConfig or None
        """
        return cls._get_market_config(market.upper())

    @classmethod
    def get_instrument(cls, market: str, instrument: str) -> Optional[InstrumentSpec]:
        """
        Get raw instrument specification by code.

        Args:
            market: Market code
            instrument: Instrument code

        Returns:
            InstrumentSpec or None
        """
        market_config = cls._get_market_config(market.upper())
        if market_config:
            return market_config.instruments.get(instrument.lower())
        return None

    @classmethod
    def get_instrument_flexible(cls, market: str, identifier: str) -> Optional[InstrumentSpec]:
        """
        Get instrument specification by either code or name.

        Supports flexible lookup:
        - By code: 'al', 'cu', 'btc'
        - By name: 'aluminum', 'copper', 'bitcoin_perpetual'

        Args:
            market: Market code (e.g., 'SHFE', 'CRYPTO')
            identifier: Instrument code or name

        Returns:
            InstrumentSpec or None
        """
        market_config = cls._get_market_config(market.upper())
        if not market_config:
            return None

        identifier_lower = identifier.lower()

        # Try as code first (most common)
        if identifier_lower in market_config.instruments:
            return market_config.instruments[identifier_lower]

        # Try as name
        for spec in market_config.instruments.values():
            if spec.name.lower() == identifier_lower:
                return spec

        return None

    @classmethod
    def list_instruments(cls, market: str) -> list:
        """
        List all instruments for a market.

        Args:
            market: Market code

        Returns:
            List of instrument codes
        """
        market_config = cls._get_market_config(market.upper())
        if market_config:
            return list(market_config.instruments.keys())
        return []

    @classmethod
    def clear_cache(cls) -> None:
        """Clear cached market configs (for testing)."""
        cls._market_configs.clear()
