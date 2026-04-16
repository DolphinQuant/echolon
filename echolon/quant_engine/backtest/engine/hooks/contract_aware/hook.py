"""
Contract-Aware Hook
===================

Hook for interday futures trading with contract rollover support.

This hook adds:
1. ContractAwareBroker: Handles position valuation across contract changes
2. ContractExpiryObserver: Forces position close before contract expiry
3. Contract price preloading: Optimization for repeated backtests

When to use:
- Futures markets with contract expiry (SHFE, CME, etc.)
- Interday trading (positions held overnight)
- NOT needed for intraday (positions flatten at session close)

Usage:
    from .hooks.contract_aware.hook import ContractAwareHook

    hook = ContractAwareHook(
        market_adapter=shfe_adapter,
        indicators_dir='/path/to/indicators',
        contract_manager=manager,  # Optional
    )
    engine.add_hook(hook)
"""

import logging
from typing import Any, Dict, Optional, TYPE_CHECKING

import backtrader as bt

from ..base import IEngineHook
from .broker import (
    create_contract_aware_broker,
    preload_contract_prices,
)
from .observer import add_contract_expiry_observer

if TYPE_CHECKING:
    from ...backtrader_engine import BacktraderEngine
    from .....core.interfaces.market_adapter import IMarketAdapter
    from .....data_loader.contract_data import ContractIndicatorManager

logger = logging.getLogger(__name__)


class ContractAwareHook(IEngineHook):
    """
    Hook for interday futures trading with contract awareness.

    Adds contract-aware broker and expiry observer to handle:
    - Position valuation during contract rollovers
    - Forced position close before contract expiry
    - Accurate PnL calculation across contracts

    Parameters:
        market_adapter: Market adapter with contract specifications
        indicators_dir: Path to indicators directory for contract prices
        contract_manager: Optional ContractIndicatorManager for extended features
        force_close_time: When to force close ('market_close' or specific time)
        log_forced_exits: Whether to log forced exit events
    """

    def __init__(
        self,
        market_adapter: 'IMarketAdapter',
        indicators_dir: str,
        contract_manager: Optional['ContractIndicatorManager'] = None,
        force_close_time: str = 'market_close',
        log_forced_exits: bool = True,
    ):
        self._market_adapter = market_adapter
        self._indicators_dir = indicators_dir
        self._contract_manager = contract_manager
        self._force_close_time = force_close_time
        self._log_forced_exits = log_forced_exits

        # Track state
        self._broker_configured = False
        self._observer_added = False

    @property
    def name(self) -> str:
        return "ContractAwareHook"

    def on_init(self, engine: 'BacktraderEngine') -> None:
        """
        Early initialization - store contract manager reference.
        """
        # Store contract manager in engine for analyzer access
        if self._contract_manager is not None:
            engine._contract_manager = self._contract_manager

        logger.debug(
            f"[{self.name}] Initialized for {self._market_adapter.market_code}"
        )

    def on_setup(self, cerebro: bt.Cerebro, engine: 'BacktraderEngine') -> None:
        """
        Configure contract-aware broker and expiry observer.
        """
        symbol = engine.get_current_symbol()

        # Pre-load contract prices for optimization performance
        preload_contract_prices(self._indicators_dir)

        # Create contract-aware broker
        contract_broker = create_contract_aware_broker(
            indicators_dir=self._indicators_dir,
            market_adapter=self._market_adapter,
            instrument=symbol,
        )

        # Set initial cash
        contract_broker.setcash(engine._initial_cash)

        # Configure commission from market adapter's contract spec
        # IMPORTANT: Must include mult for futures to calculate P&L correctly
        contract_spec = self._market_adapter.get_contract_spec(symbol)
        if contract_spec is not None:
            if contract_spec.commission_type == "percentage":
                contract_broker.setcommission(
                    commission=contract_spec.commission,
                    mult=contract_spec.multiplier
                )
            else:
                contract_broker.setcommission(
                    commission=contract_spec.commission,
                    commtype=bt.CommInfoBase.COMM_FIXED,
                    mult=contract_spec.multiplier
                )

        # Replace default broker
        cerebro.setbroker(contract_broker)
        self._broker_configured = True

        logger.info(
            f"[{self.name}] ContractAwareBroker configured for {symbol}"
        )

        # Add contract expiry observer
        add_contract_expiry_observer(
            cerebro=cerebro,
            market_adapter=self._market_adapter,
            force_close_time=self._force_close_time,
            log_forced_exits=self._log_forced_exits,
        )
        self._observer_added = True

        logger.info(f"[{self.name}] ContractExpiryObserver added")

    def on_post_setup(self, cerebro: bt.Cerebro, engine: 'BacktraderEngine') -> None:
        """
        Post-setup validation.
        """
        if not self._broker_configured:
            logger.warning(f"[{self.name}] Broker was not configured during setup")

    def on_pre_run(self, engine: 'BacktraderEngine') -> None:
        """
        Pre-run validation.
        """
        logger.debug(
            f"[{self.name}] Pre-run check: "
            f"broker={self._broker_configured}, observer={self._observer_added}"
        )

    def on_post_run(
        self,
        engine: 'BacktraderEngine',
        strategy: bt.Strategy,
        results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Extract contract-aware metrics if available.
        """
        # Contract-aware trades are extracted by analyzers, not here
        # This hook just ensures the infrastructure was in place

        results['contract_aware_enabled'] = True
        results['contract_awareness'] = {
            'broker_configured': self._broker_configured,
            'observer_added': self._observer_added,
            'indicators_dir': self._indicators_dir,
        }

        logger.debug(f"[{self.name}] Post-run complete")

        return results

    def __repr__(self) -> str:
        return (
            f"ContractAwareHook("
            f"market={self._market_adapter.market_code}, "
            f"indicators_dir={self._indicators_dir})"
        )
