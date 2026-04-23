"""
Indicators Module Entry Point
=============================

Main orchestrator for technical indicator calculation.
Uses data_pipeline loaders for standardized data access.

Output directory: workspace/data/indicators/backtest/{instrument}/
"""
import os
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime
import pandas as pd

from echolon.config.markets.core.context import TradingContext
from echolon.indicators.schema import IndicatorList

logger = logging.getLogger(__name__)


def run_indicator_calculation(
    ctx: TradingContext,
    output_dir: str,
    indicator_list: Dict[str, Dict[str, Any]],
    *,
    trading_dates: Optional[List[datetime]] = None,
    use_parallel: bool = True,
    regime_params: Optional[Dict[str, Any]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    paths: Optional["PathsConfig"] = None,  # type: ignore[name-defined]
) -> pd.DataFrame:
    """
    Run indicator calculation on market data.

    This orchestrates:
    1. Loading OHLCV data via data_pipeline loaders
    2. Calculating technical indicators for each contract
    3. Extracting main contract indicators
    4. Saving results

    Args:
        ctx: TradingContext with market, instrument, frequency configuration.
        output_dir: Directory to save indicator files.
        indicator_list: Flat-dict indicator specification passed directly to
            :class:`IndicatorProcessor`.  Keys are indicator names (lower-case);
            values are param dicts supporting Cartesian sweeps.  For example::

                {"rsi": {"timeperiod": [5, 30]}, "market_regime": {}}

        trading_dates: List of trading dates to process (optional; loads from calendar if None).
            If None, start_date and end_date are required and used to load calendar dates.
        use_parallel: Use parallel processing.
        regime_params: Regime classification parameters required when
            *indicator_list* contains ``market_regime`` on an interday ctx.
            Call ``echolon.indicators.optimize_regime_params(ctx)`` and pass here.
        start_date: ISO date string for backtest start (e.g. ``"2018-01-01"``).
            Required if trading_dates is None.
        end_date: ISO date string for backtest end.
            Required if trading_dates is None.

    Returns:
        DataFrame with main contract indicators.

    Raises:
        ValueError: If trading_dates is None and start_date/end_date are not provided.

    Example:
        >>> from echolon.config.markets.factory import MarketFactory
        >>> ctx = MarketFactory.create(
        ...     market='SHFE', instrument='al', frequency='interday', bar_size='1d',
        ... )
        >>> indicators = run_indicator_calculation(
        ...     ctx,
        ...     output_dir="/path/to/output",
        ...     indicator_list={"rsi": {"timeperiod": [5, 30]}},
        ...     regime_params=my_regime_params,
        ...     start_date="2018-01-01",
        ...     end_date="2024-12-31",
        ... )
    """
    # Validate indicator_list schema early for fail-fast
    IndicatorList.model_validate(indicator_list)

    # Extract from TradingContext
    market = ctx.market_code
    instrument = ctx.instrument_name
    is_intraday = ctx.is_intraday

    # Map frequency for processor: interday -> "day", intraday -> "minute"
    processor_frequency = "minute" if is_intraday else "day"

    logger.info(
        f"[INDICATORS] Starting | market={market}, instrument={instrument}, "
        f"freq={processor_frequency}, indicators={len(indicator_list)}"
    )

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    logger.info(f"[INDICATORS] Output directory | path={output_dir}")

    # Load trading dates if not provided
    if trading_dates is None:
        if start_date is None or end_date is None:
            raise ValueError(
                "start_date and end_date are required when trading_dates is None. "
                "Pass both start_date and end_date, or provide trading_dates directly."
            )
        trading_dates = _load_trading_dates(market, instrument, start_date, end_date)

    logger.info(f"[INDICATORS] Processing {len(trading_dates)} trading dates")

    # Import and create processor
    from .engine.processor import IndicatorProcessor

    # Derive backtest_start_year from start_date if available
    backtest_start_year = None
    if start_date is not None:
        backtest_start_year = int(start_date[:4])

    processor = IndicatorProcessor(
        ctx=ctx,
        trading_date_list=trading_dates,
        indicator_list=indicator_list,
        output_dir=output_dir,
        regime_params=regime_params,
        backtest_start_year=backtest_start_year,
    )

    # Process all contracts
    result = processor.process_all_contracts(use_multiprocessing=use_parallel)

    if isinstance(result, pd.DataFrame) and not result.empty:
        logger.info(f"[INDICATORS] Complete | rows={len(result)}")
    else:
        logger.warning("[INDICATORS] Complete | no data returned")

    return result


def _load_trading_dates(
    market: str,
    instrument: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> List[datetime]:
    """Load trading dates from calendar."""
    from echolon.data.loaders.calendar_loader import get_trading_dates

    dates = get_trading_dates(
        market=market,
        asset=instrument,
        start_date=start_date,
        end_date=end_date,
    )

    return dates



