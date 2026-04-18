"""
Contract Expiry Observer for Backtesting
=========================================

Observer that monitors contract expiration dates and signals forced exits
before the actual contract expiry.

MIGRATED FROM: modules/backtest/backtesting/engine/contract_expiry_observer.py
Changes:
- Parameterized with IMarketAdapter instead of hardcoded date calculations
- Uses market_adapter.get_contract_expiry_date() for expiry determination
- Uses market_adapter.get_previous_trading_day() for trading calendar
- Uses market_adapter.parse_contract() for contract parsing
- Works with any market that implements IMarketAdapter

Force exit rule: Signal forced exit TWO trading days before contract expiry.
Signal -> Execute Next Day -> Still Before Expiry
"""

import backtrader as bt
import datetime
import logging
from typing import Optional, Dict, Any, List, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from echolon.markets.interface import IMarketAdapter

logger = logging.getLogger(__name__)


class ContractExpiryObserver(bt.Observer):
    """
    Observer that monitors contract expiry and signals forced exits.

    Key logic:
    1. On each bar, check if there's an active position
    2. Get contract code from active position
    3. Use market_adapter to calculate expiry date
    4. Signal forced exit TWO trading days before expiry
    5. Mark contract as signaled to prevent duplicates

    Parameters
    ----------
    market_adapter : IMarketAdapter
        Market adapter for calendar and contract management
    force_close_time : str
        When to close: 'market_open' or 'market_close'
    log_forced_exits : bool
        Whether to log forced exits
    """

    lines = ('expiry_status',)

    params = (
        ('market_adapter', None),  # IMarketAdapter instance
        ('force_close_time', 'market_close'),
        ('log_forced_exits', True),
    )

    def __init__(self):
        """Initialize the contract expiry observer."""
        super().__init__()

        # Track forced exits for reporting
        self.forced_exits: List[Dict[str, Any]] = []
        self.bar_count = 0

        # Track positions that have been signaled for forced exit
        self.signaled_contracts = set()

        # Store market adapter reference
        self.market_adapter = self.p.market_adapter

        if self.market_adapter is None:
            logger.warning("[EXPIRY_OBSERVER] No market_adapter provided | forced exits may not work")
        elif self.market_adapter.has_contract_expiry:
            if logger.isEnabledFor(logging.INFO):
                logger.info(f"[EXPIRY_OBSERVER] Initialized | market={self.market_adapter.market_code}")
        else:
            logger.info("[EXPIRY_OBSERVER] Market has no contract expiry (perpetuals)")

    def _calculate_force_exit_signal_date(self, contract_code: str) -> Optional[datetime.datetime]:
        """
        Calculate when to SIGNAL force exit: TWO trading days before contract expiry.

        For contract al2004 (April 2020):
        1. Get expiry date from market_adapter
        2. Signal TWO trading days before expiry
        3. Order executes the NEXT day
        4. Position closed BEFORE expiry

        Parameters
        ----------
        contract_code : str
            Contract code (e.g., 'al2004')

        Returns
        -------
        Optional[datetime.datetime]
            Date to signal forced exit, or None if calculation fails
        """
        if self.market_adapter is None:
            return None

        # Get expiry date from market adapter
        expiry_date = self.market_adapter.get_contract_expiry_date(contract_code)

        if expiry_date is None:
            logger.warning(f"[EXPIRY_OBSERVER] No expiry date | contract={contract_code}")
            return None

        # Convert to datetime if needed
        if isinstance(expiry_date, datetime.date) and not isinstance(expiry_date, datetime.datetime):
            expiry_datetime = datetime.datetime.combine(expiry_date, datetime.time())
        else:
            expiry_datetime = expiry_date

        # Get TWO trading days before expiry (signal date)
        # Signal -> Execute Next Day -> Still Before Expiry
        one_day_before = self.market_adapter.get_previous_trading_day(expiry_date)
        if one_day_before is None:
            logger.warning(f"[EXPIRY_OBSERVER] Calendar calc failed | contract={contract_code}, step=one_day_before")
            return None

        signal_date = self.market_adapter.get_previous_trading_day(one_day_before)
        if signal_date is None:
            logger.warning(f"[EXPIRY_OBSERVER] Calendar calc failed | contract={contract_code}, step=two_days_before")
            return None

        # Convert to datetime for comparison
        if isinstance(signal_date, datetime.date) and not isinstance(signal_date, datetime.datetime):
            signal_datetime = datetime.datetime.combine(signal_date, datetime.time())
        else:
            signal_datetime = signal_date

        # Log expiry calculation at INFO level for visibility
        logger.info(
            f"[EXPIRY_OBSERVER] Expiry calc | contract={contract_code}, "
            f"expiry={expiry_date}, signal_date={signal_datetime.strftime('%Y-%m-%d')}"
        )

        return signal_datetime

    def _get_current_trading_date(self) -> datetime.datetime:
        """Get the current trading date from the data feed."""
        return self.data.datetime.datetime(0)

    def _get_current_position(self) -> Optional[Any]:
        """
        Get current position using enhanced broker with contract information.

        Returns position object with attributes:
        - size: position size
        - contract: contract code

        IMPORTANT: Must get position from BROKER (not strategy) to access
        EnhancedPosition with contract attribute set by ContractAwareBroker.
        """
        # Get broker from strategy - this is the ContractAwareBroker
        broker = self._owner.broker
        if broker is None:
            return None

        # Use broker's helper method to find any active position with contract info
        # This avoids data key mismatch issues between observer.data and order.data
        if hasattr(broker, 'get_current_position_with_contract'):
            position = broker.get_current_position_with_contract()
            if position is not None:
                return position

        # Fallback: try direct lookup with observer's data reference
        position = broker.getposition(self.data)
        return position

    def _should_signal_forced_exit(self) -> Tuple[bool, str, str]:
        """
        Check if we should signal a forced exit.

        Returns
        -------
        Tuple[bool, str, str]
            (should_signal, reason, contract_code)
        """
        # Skip if market has no contract expiry (perpetuals)
        if self.market_adapter is not None and not self.market_adapter.has_contract_expiry:
            return False, "Market has no contract expiry", ""

        current_date = self._get_current_trading_date()

        # Get current position
        position = self._get_current_position()

        # Debug: Log position retrieval result
        if position is None:
            logger.debug(f"[EXPIRY_OBSERVER] Position is None | date={current_date.date()}")
            return False, "No position object available", ""

        # Check if there's an active position
        position_size = getattr(position, 'size', 0)
        contract_code = getattr(position, 'contract', None)

        # Log position details when there IS a position (INFO level for visibility)
        if position_size != 0:
            logger.info(
                f"[EXPIRY_OBSERVER] Active position found | date={current_date.date()}, "
                f"size={position_size}, contract={contract_code}"
            )

        if position_size == 0:
            return False, "No active position", ""

        if not contract_code:
            # Debug: Log when contract is missing but position exists
            logger.warning(
                f"[EXPIRY_OBSERVER] Position without contract | "
                f"date={current_date.date()}, size={position_size}, "
                f"position_type={type(position).__name__}"
            )
            return False, "No contract code available", ""

        # Check if already signaled for this contract
        if contract_code in self.signaled_contracts:
            return False, f"Already signaled for {contract_code}", contract_code

        # Calculate signal date
        signal_date = self._calculate_force_exit_signal_date(contract_code)

        if signal_date is None:
            return False, f"Could not calculate signal date for {contract_code}", contract_code

        # Check if today is ON OR AFTER the signal date (fix: >= instead of ==)
        # This ensures expiry signal is triggered even if missed on exact signal date
        if current_date.date() < signal_date.date():
            return False, f"Before signal date: current={current_date.date()}, signal={signal_date.date()}", contract_code

        # All conditions met
        reason = f"Contract {contract_code} expiry signal: position_size={position_size}, signal_date={signal_date.date()}"
        return True, reason, contract_code

    def _signal_forced_exit_required(self, reason: str, contract_code: str) -> bool:
        """Signal that a forced exit is required to the strategy."""
        position = self._get_current_position()
        if position is None:
            logger.error("[EXPIRY_OBSERVER] Signal failed | reason=No position available")
            return False

        position_size = getattr(position, 'size', 0)
        current_date = self._get_current_trading_date()
        current_price = self.data.close[0]

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                f"[EXPIRY_OBSERVER] Signaling exit | contract={contract_code}, "
                f"size={position_size}, price={current_price}"
            )

        # Signal the strategy
        if hasattr(self._owner, 'agnostic_strategy'):
            agnostic_strategy = self._owner.agnostic_strategy

            forced_exit_data = {
                'required': True,
                'reason': reason,
                'contract_code': contract_code,
                'position_size': position_size,
                'observer_date': current_date.isoformat(),
                'current_price': float(current_price)
            }

            setattr(agnostic_strategy, '_forced_exit_signal', forced_exit_data)

            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    f"[EXPIRY_OBSERVER] Signal set | contract={contract_code}, "
                    f"position_size={position_size}"
                )

            # Mark contract as signaled
            self.signaled_contracts.add(contract_code)

            # Track the forced exit
            forced_exit_info = {
                'date': current_date.isoformat(),
                'contract_code': contract_code,
                'position_size': position_size,
                'close_price': float(current_price),
                'reason': f"contract_expiry_signal - {reason}",
                'status': 'signaled_to_strategy'
            }
            self.forced_exits.append(forced_exit_info)

            if hasattr(self._owner, 'log'):
                self._owner.log(
                    f"FORCED EXIT SIGNAL: Contract {contract_code} expiry - "
                    f"Size: {position_size}, Price: {current_price:.2f}"
                )

            return True
        else:
            logger.error("[EXPIRY_OBSERVER] Signal failed | reason=Strategy missing agnostic_strategy")
            return False

    def next(self):
        """Called on each bar to check for contract expiry."""
        self.bar_count += 1

        expiry_action = 0

        # Log first bar to confirm observer is running
        if self.bar_count == 1:
            current_date = self._get_current_trading_date()
            broker = getattr(self._owner, 'broker', None)
            broker_type = type(broker).__name__ if broker else 'None'
            logger.info(
                f"[EXPIRY_OBSERVER] First bar | date={current_date.date()}, "
                f"broker_type={broker_type}, market={self.market_adapter.market_code if self.market_adapter else 'None'}"
            )

        should_signal, reason, contract_code = self._should_signal_forced_exit()

        # Debug: Log when there's a position but no signal
        if not should_signal and contract_code:
            logger.debug(f"[EXPIRY_OBSERVER] No signal | reason={reason}")

        if should_signal:
            if logger.isEnabledFor(logging.INFO):
                logger.info(f"[EXPIRY_OBSERVER] Triggering exit | {reason}")
            if self._signal_forced_exit_required(reason, contract_code):
                expiry_action = 1

        self.lines.expiry_status[0] = expiry_action

    def get_forced_exits(self) -> List[Dict[str, Any]]:
        """Get list of all forced exits that occurred during the backtest."""
        return self.forced_exits.copy()

    def get_analysis(self) -> Dict[str, Any]:
        """Get analysis results from the observer."""
        return {
            'total_forced_exits': len(self.forced_exits),
            'forced_exits_details': self.forced_exits.copy(),
            'total_bars_processed': self.bar_count,
            'signaled_contracts': list(self.signaled_contracts),
            'observer_params': {
                'force_close_time': self.p.force_close_time,
                'market': self.market_adapter.market_code if self.market_adapter else None
            }
        }


def add_contract_expiry_observer(
    cerebro: bt.Cerebro,
    market_adapter: 'IMarketAdapter',
    force_close_time: str = 'market_close',
    log_forced_exits: bool = True
) -> None:
    """
    Add contract expiry observer to the cerebro engine.

    Parameters
    ----------
    cerebro : bt.Cerebro
        The Backtrader cerebro engine
    market_adapter : IMarketAdapter
        Market adapter for calendar and contract management
    force_close_time : str, optional
        When to force close ('market_open' or 'market_close')
    log_forced_exits : bool, optional
        Whether to log forced exits
    """
    cerebro.addobserver(
        ContractExpiryObserver,
        market_adapter=market_adapter,
        force_close_time=force_close_time,
        log_forced_exits=log_forced_exits
    )
