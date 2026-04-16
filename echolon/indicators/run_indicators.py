"""
Indicators Module Entry Point
=============================

Main orchestrator for technical indicator calculation.
Uses data_pipeline loaders for standardized data access.

Output directories:
- selected_only=True  → workspace/data/indicators/backtest/{instrument}/
- selected_only=False → workspace/data/indicators/research/{instrument}/
"""
import os
import logging
from typing import List, Optional
from datetime import datetime
import pandas as pd

from echolon.config.settings import INDICATORS_BACKTEST_DIR, INDICATORS_RESEARCH_DIR
from echolon.config.quant_engine import BACKTEST_START_DATE, BACKTEST_END_DATE
from echolon.config.markets.core.context import TradingContext

logger = logging.getLogger(__name__)


def run_indicator_calculation(
    ctx: TradingContext,
    output_dir: Optional[str] = None,
    trading_dates: Optional[List[datetime]] = None,
    selected_only: bool = True,
    use_parallel: bool = True,
    mode: str = 'backtest',
    optimize_regime: bool = False,
    indicator_config: Optional[dict] = None,
    regime_params: Optional[dict] = None,
) -> pd.DataFrame:
    """
    Run indicator calculation on market data.

    This orchestrates:
    1. Loading OHLCV data via data_pipeline loaders
    2. Calculating technical indicators for each contract
    3. Extracting main contract indicators
    4. Saving results

    Args:
        ctx: TradingContext with market, instrument, frequency configuration
        output_dir: Directory to save indicator files (auto-selected if None)
        trading_dates: List of trading dates to process (loads from calendar if None)
        selected_only: Only calculate strategy-required indicators.
                       If True, saves to workspace/data/indicators/backtest/
                       If False, saves to workspace/data/indicators/research/
        use_parallel: Use parallel processing
        optimize_regime: Run regime parameter optimization
        indicator_config: Optional pre-loaded indicator config dict.
            If provided, IndicatorProcessor uses this instead of loading
            from strategy_indicator_list.json.
        regime_params: Optional pre-loaded regime params dict.
            If provided, IndicatorProcessor uses this instead of loading
            from output/regime_params.json or running optimization.
            Each strategy cluster has its own regime params.

    Returns:
        DataFrame with main contract indicators

    Example:
        >>> from config.markets.factory import MarketFactory
        >>> ctx = MarketFactory.from_session()
        >>> indicators = run_indicator_calculation(ctx, selected_only=False)
    """
    # Extract from TradingContext
    market = ctx.market_code
    instrument = ctx.instrument_name
    is_intraday = ctx.is_intraday

    # Map frequency for processor: interday -> "day", intraday -> "minute"
    processor_frequency = "minute" if is_intraday else "day"

    logger.info(
        f"[INDICATORS] Starting | market={market}, instrument={instrument}, "
        f"freq={processor_frequency}, selected_only={selected_only}"
    )

    # Set default output directory based on selected_only flag
    if output_dir is None:
        if selected_only:
            # Strategy-selected indicators for backtesting
            base_dir = INDICATORS_BACKTEST_DIR
        else:
            # Full indicators for research/analysis
            base_dir = INDICATORS_RESEARCH_DIR

        output_dir = os.path.join(base_dir, instrument)
        os.makedirs(output_dir, exist_ok=True)
        logger.info(f"[INDICATORS] Output directory | path={output_dir}")

    # Load trading dates if not provided
    if trading_dates is None:
        if mode == 'backtest':
            trading_dates = _load_trading_dates(market, instrument, BACKTEST_START_DATE, BACKTEST_END_DATE)
        if mode == 'deploy':
            trading_dates = _load_trading_dates(market, instrument)

    logger.info(f"[INDICATORS] Processing {len(trading_dates)} trading dates")

    # Import and create processor
    from .engine.processor import IndicatorProcessor

    processor = IndicatorProcessor(
        ctx=ctx,
        trading_date_list=trading_dates,
        output_dir=output_dir,
        selected=selected_only,
        indicator_config=indicator_config,
        regime_params=regime_params,
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
    from echolon.data_pipeline.loaders.calendar_loader import get_trading_dates

    dates = get_trading_dates(
        market=market,
        asset=instrument,
        start_date=start_date,
        end_date=end_date,
    )

    return dates



