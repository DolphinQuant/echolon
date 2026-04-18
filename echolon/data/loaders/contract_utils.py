"""
Trading Utilities
=================

Thin wrappers around the canonical main-contract resolution in
``modules.quant_engine.market_adapters.shfe.contract_rules``.

The canonical function returns the bare code (e.g. ``'al2403'``).
Deploy / xtquant callers need the ``.SF`` exchange suffix, so the
wrappers here simply append it.
"""

import logging
from datetime import datetime

from ...market_adapters.shfe.contract_rules import (
    get_main_contract as _get_main_contract_canonical,
)

logger = logging.getLogger(__name__)

# Default symbol used throughout the deploy pipeline
_DEFAULT_SYMBOL = "al"


def get_main_contract(ref_date: datetime = None, symbol: str = _DEFAULT_SYMBOL) -> str:
    """
    Get the main futures contract code with ``.SF`` exchange suffix.

    Delegates to the canonical CSV-based lookup in
    ``market_adapters.shfe.contract_rules.get_main_contract``.

    Args:
        ref_date: Reference date. Defaults to ``datetime.now()`` if not provided.
        symbol: Product symbol (e.g. ``'al'``, ``'cu'``). Defaults to ``'al'``.

    Returns:
        Main contract code with suffix (e.g. ``'al2508.SF'``).
    """
    current_date = ref_date if ref_date is not None else datetime.now()
    trading_date = current_date.date() if isinstance(current_date, datetime) else current_date

    bare_code = _get_main_contract_canonical(trading_date, symbol)
    contract = f"{bare_code}.SF"

    logger.debug(f"Main contract for {trading_date}: {contract}")
    return contract


