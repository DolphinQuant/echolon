"""
Data Pipeline Entry Point
=========================

Main orchestrator for market data extraction and preprocessing.

Data Flow:
- Source: data/{market}/{instrument_code}/     (raw data from API/extractor)
- Output: workspace/data/market_data/     (processed data for consumers)

Separation of Concerns:
- Extractors: Retrieve raw data from sources (files, APIs) → save to data/
- Transformers: Process and standardize data
- Loaders: Provide data access for downstream consumers
"""
import logging
from pathlib import Path
from typing import Optional
import pandas as pd

from echolon.config.settings import MARKET_DATA_DIR, RAW_DATA_DIR
from echolon.config.markets.factory import MarketFactory
from echolon.config.markets.core.context import TradingContext
from .transformers.ohlcv_standardizer import OHLCVStandardizer
from .transformers.session_filter import SessionFilter
from .transformers.ohlcv_resampler import OHLCVResampler
from .transformers.contract_splitter import ContractSplitter
from .transformers.calendar_generator import CalendarGenerator
from .transformers.shfe_session_analyzer import SHFESessionAnalyzer
from .loaders.calendar_loader import get_trading_calendar_instance

logger = logging.getLogger(__name__)


def run_data_pipeline(
    ctx: TradingContext,
    input_dir: Optional[str] = None,
    output_dir: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    skip_extraction: bool = False,
    skip_standardization: bool = False,
    skip_splitting: bool = False,
    skip_calendar: bool = False,
    # Minute-specific options
    start_contract: Optional[str] = None,
    # Live source options (for deploy / MiniQMT)
    source: str = "file",
    client=None,
    present_date=None,
) -> bool:
    """
    Run the complete data pipeline.

    This orchestrates:
    1. Raw data extraction from exchange files or API (Extractor)
    1.5. Generate trading calendar (must happen before standardization)
    2. Data standardization (Transformer: OHLCVStandardizer)
    3. Session filtering - remove out-of-session bars (Transformer: SessionFilter)
    4. Resampling to target frequency (Transformer: OHLCVResampler)
    5. Splitting data by contract (Transformer: ContractSplitter)

    Note: Calendar generation happens early (Step 1.5) because OHLCVStandardizer
    needs it to correctly assign trading_date for night session bars.

    For minute data from API, Step 1 also downloads OHLCV for each contract.

    For live sources (source="qmt"), the pipeline uses incremental downloads
    and API-based calendar updates instead of file-based extraction.

    Args:
        ctx: TradingContext with market, instrument, frequency configuration
        input_dir: Raw data input directory (optional, uses default)
        output_dir: Processed data output directory (optional, uses default)
        start_date: Start date for filtering (YYYY-MM-DD)
        end_date: End date for filtering (YYYY-MM-DD)
        skip_extraction: Skip raw data extraction step
        skip_standardization: Skip data standardization step
        skip_splitting: Skip contract splitting step
        skip_calendar: Skip calendar generation step
        start_contract: For minute API data - starting contract code (e.g., "2301")
        source: Data source - "file" for local files (default),
                "qmt" for MiniQMT live connection
        client: MiniQMT client instance (required when source="qmt")
        present_date: Reference date for live pipeline (default: now)

    Returns:
        True if successful

    Example:
        >>> from config.markets.factory import MarketFactory
        >>> ctx = MarketFactory.from_session()
        >>> run_data_pipeline(ctx, skip_extraction=True)
    """
    # Extract from TradingContext
    market = ctx.market_code
    instrument = ctx.instrument_name
    is_intraday = ctx.is_intraday
    bar_size = ctx.bar_size
    timezone = ctx.timezone

    logger.info(
        f"[DATA_PIPELINE] Starting | market={market}, instrument={instrument}, "
        f"frequency={'intraday' if is_intraday else 'interday'}, bar_size={bar_size}"
    )

    # Determine output directory: workspace/data/market_data/{market}/{instrument}/
    raw_data_output_dir = input_dir
    output_path = Path(output_dir) if output_dir else MARKET_DATA_DIR / market / instrument
    output_path.mkdir(parents=True, exist_ok=True)

    # Map frequency for extractor: interday -> "day", intraday -> "minute"
    extractor_frequency = "minute" if is_intraday else "day"

    # Select extractor based on market, frequency, and source
    is_live = source != "file"
    extractor = _get_extractor(market, instrument, extractor_frequency, source=source)

    # Inject client and present_date for live extractors
    if client is not None and hasattr(extractor, 'set_client'):
        extractor.set_client(client)
    if present_date is not None and hasattr(extractor, 'present_date'):
        extractor.present_date = present_date

    raw_data = None

    # Step 1: Extract raw data (Extractor responsibility)
    if not skip_extraction:
        if is_live and hasattr(extractor, 'update_incremental'):
            # Live source: incremental update (only download new bars)
            # Save per-contract CSVs into {futures_code}_by_contract/ subdirectory
            # to match downstream expectations (indicator_calculator, data_loader)
            contract_data_dir = str(
                output_path / f"{extractor.futures_code}_by_contract"
            )
            logger.info(
                f"[DATA_PIPELINE] Step 1: Incremental update via live source "
                f"→ {contract_data_dir}"
            )
            raw_data = extractor.extract_raw(output_dir=contract_data_dir, save=False)
            if raw_data is None or raw_data.empty:
                logger.error("[DATA_PIPELINE] Live incremental update failed: no data")
                return False
            logger.info(f"[DATA_PIPELINE] Incremental update: {len(raw_data)} rows")
        else:
            # File source: full extraction
            logger.info("[DATA_PIPELINE] Step 1: Extracting raw data")
            raw_data = extractor.extract_raw(
                input_dir=input_dir,
                output_dir=str(output_path),
                start_date=start_date,
                end_date=end_date
            )
            if raw_data.empty:
                logger.error("[DATA_PIPELINE] Extraction failed: no data")
                return False
            logger.info(f"[DATA_PIPELINE] Extracted {len(raw_data)} rows")

            # For minute API extraction, also download OHLCV data per contract
            if is_intraday and hasattr(extractor, 'download_minute_data'):
                logger.info("[DATA_PIPELINE] Step 1b: Downloading minute OHLCV data")
                if start_contract:
                    success = extractor.download_minute_data(
                        start_contract=start_contract,
                        period="1m",
                        output_dir=str(output_path)
                    )
                    if not success:
                        logger.error("[DATA_PIPELINE] Minute data download failed")
                        return False
    else:
        # Load existing raw data from source directory
        logger.info("[DATA_PIPELINE] Step 1: Loading existing raw data (extraction skipped)")
        raw_data = _load_source_data(market, instrument, extractor_frequency)
        if raw_data is None or raw_data.empty:
            logger.error("[DATA_PIPELINE] No existing data found to process")
            return False
        logger.info(f"[DATA_PIPELINE] Loaded {len(raw_data)} rows from source")

    # Step 1.5: Generate trading calendar BEFORE standardization
    if is_live and hasattr(extractor, 'generate_trading_calendar'):
        # Live source: API-based calendar with historical/future merge
        if not skip_calendar:
            logger.info("[DATA_PIPELINE] Step 1.5: Updating trading calendar from live source")
            calendar = extractor.generate_trading_calendar(
                output_dir=str(output_path),
            )
            if not calendar.empty:
                logger.info(
                    f"[DATA_PIPELINE] Trading calendar updated: {len(calendar)} dates"
                )
            else:
                logger.warning("[DATA_PIPELINE] Trading calendar update returned empty")
    else:
        # File source: derive calendar from data if it doesn't exist
        _generate_calendar_if_needed(
            raw_data=raw_data,
            output_path=output_path,
            start_date=start_date,
            end_date=end_date,
            skip_calendar=skip_calendar,
            timezone=timezone
        )

    # Step 2: Standardize data (Transformer responsibility)
    if not skip_standardization and raw_data is not None:
        logger.info("[DATA_PIPELINE] Step 2: Standardizing data")
        # Load trading calendar for intraday trading_date calculation
        trading_calendar = get_trading_calendar_instance(market, instrument)
        standardizer = OHLCVStandardizer(
            fill_missing=True,
            market=market,
            trading_calendar=trading_calendar,
            bar_size=bar_size,  # Pass bar_size for correct session phase names
        )
        raw_data = standardizer.standardize(raw_data, timezone=timezone)
        logger.info(f"[DATA_PIPELINE] Standardized {len(raw_data)} rows")

    # Step 2.5: Analyze session availability (SHFE intraday only)
    # Detects which sessions were active for each trading date (handles holidays)
    if is_intraday and raw_data is not None and market.upper() == "SHFE":
        logger.info("[DATA_PIPELINE] Step 2.5: Analyzing SHFE session availability")
        _analyze_shfe_sessions(
            standardized_data=raw_data,
            output_path=output_path,
            bar_size=bar_size
        )

    # Step 3: Filter out-of-session bars (for intraday only)
    # Removes bars during breaks and outside trading hours
    if is_intraday and raw_data is not None:
        logger.info("[DATA_PIPELINE] Step 3: Filtering out-of-session bars")
        session_filter = SessionFilter(market=market)
        raw_data = session_filter.filter(raw_data)

    # Step 4: Resample to target frequency (for intraday only)
    # Converts 1-minute bars to user-specified frequency (e.g., 5m, 15m, 1h)
    if is_intraday and raw_data is not None and bar_size != "1m":
        logger.info(f"[DATA_PIPELINE] Step 4: Resampling to {bar_size}")
        resampler = OHLCVResampler(target_frequency=bar_size)
        raw_data = resampler.resample(raw_data)
        logger.info(f"[DATA_PIPELINE] Resampled to {len(raw_data)} rows")

    # Step 5: Split by contract (Transformer responsibility)
    # Live extractors already save per-contract CSVs during extraction
    if not skip_splitting and raw_data is not None:
        logger.info("[DATA_PIPELINE] Step 5: Splitting by contract")
        splitter = ContractSplitter(output_dir=str(output_path))
        contracts = splitter.split(raw_data)
        logger.info(f"[DATA_PIPELINE] Split into {len(contracts)} contracts")

    # Note: Calendar generation moved to Step 1.5 (before standardization)
    # to ensure calendar exists when OHLCVStandardizer calculates trading_date

    logger.info("[DATA_PIPELINE] Complete")
    return True


def _generate_calendar_if_needed(
    raw_data: pd.DataFrame,
    output_path: Path,
    start_date: Optional[str],
    end_date: Optional[str],
    skip_calendar: bool,
    timezone: str = None
) -> None:
    """
    Generate trading calendar from raw data if it doesn't already exist.

    This must run BEFORE standardization because OHLCVStandardizer needs
    the calendar to correctly assign trading_date for night session bars.

    Args:
        raw_data: Raw OHLCV data with datetime information
        output_path: Directory to save calendar file
        start_date: Optional start date filter
        end_date: Optional end date filter
        skip_calendar: If True, skip calendar generation
        timezone: Timezone for epoch timestamp conversion (e.g., 'Asia/Shanghai').
                  Required for intraday data with epoch millisecond timestamps.
    """
    if skip_calendar or raw_data is None:
        return

    calendar_file = output_path / "trading_calendar.csv"

    # Skip if calendar already exists
    if calendar_file.exists():
        logger.info(f"[DATA_PIPELINE] Trading calendar exists, skipping generation: {calendar_file}")
        return

    logger.info("[DATA_PIPELINE] Generating trading calendar (required for standardization)")
    calendar_gen = CalendarGenerator(output_dir=str(output_path), timezone=timezone)
    calendar = calendar_gen.generate(
        df=raw_data,
        start_date=start_date,
        end_date=end_date
    )
    logger.info(f"[DATA_PIPELINE] Generated calendar with {len(calendar)} trading days")


def _get_extractor(market: str, instrument: str, frequency: str, source: str = "file"):
    """Get the appropriate extractor for market/frequency combination.

    Args:
        market: Market code (e.g., "SHFE")
        instrument: Instrument name (e.g., "aluminum")
        frequency: Data frequency ("day", "minute", etc.)
        source: Data source - "file" for local files (default),
                "qmt" for MiniQMT live connection
    """
    market_upper = market.upper()

    if market_upper == "SHFE":
        if frequency == "day" and source == "qmt":
            from .extractors.shfe.live_day_extractor import SHFELiveDayExtractor
            return SHFELiveDayExtractor(market, instrument)
        elif frequency == "day":
            from .extractors.shfe.day_extractor import SHFEDayExtractor
            return SHFEDayExtractor(market, instrument)
        elif frequency in ("minute", "1m", "5m", "15m", "1h"):
            from .extractors.shfe.minute_extractor import SHFEMinuteExtractor
            return SHFEMinuteExtractor(market, instrument)
        else:
            raise ValueError(f"Unsupported frequency: {frequency}")

    elif market_upper == "CRYPTO":
        # TODO: Implement crypto extractor
        raise NotImplementedError("Crypto extractor not yet implemented")

    else:
        raise ValueError(f"Unsupported market: {market}")


def _load_source_data(market: str, instrument: str, frequency: str) -> Optional[pd.DataFrame]:
    """
    Load existing raw data from source directory.

    Source locations:
    - Day data: data/{market}/raw_data/*.xls* or data/{market}/{instrument_code}/sort_by_date.csv
    - Minute data: data/{market}/{instrument_code}/minute_data/*.csv

    Args:
        market: Market code (e.g., "SHFE")
        instrument: Instrument name (e.g., "aluminum")
        frequency: Data frequency ("day", "minute", etc.)

    Returns:
        DataFrame with combined data, or None if not found
    """
    # Get instrument code using MarketFactory (supports both code and name lookup)
    instrument_spec = MarketFactory.get_instrument_flexible(market, instrument)
    instrument_code = instrument_spec.code
    is_minute = frequency in ("minute", "1m", "5m", "15m", "1h")

    if is_minute:
        # Load minute data: multiple per-contract files
        source_dir = RAW_DATA_DIR / market / instrument_code / "minute_data"
        if not source_dir.exists():
            logger.warning(f"[DATA_PIPELINE] Minute data directory not found: {source_dir}")
            return None

        csv_files = list(source_dir.glob("*.csv"))
        if not csv_files:
            logger.warning(f"[DATA_PIPELINE] No CSV files found in {source_dir}")
            return None

        logger.info(f"[DATA_PIPELINE] Loading {len(csv_files)} contract files from {source_dir}")

        all_data = []
        for csv_file in csv_files:
            df = pd.read_csv(csv_file)
            # Add contract column from filename if not present
            if 'contract' not in df.columns:
                contract_name = csv_file.stem  # e.g., "al2301"
                df['contract'] = contract_name
            all_data.append(df)

        if not all_data:
            return None

        combined = pd.concat(all_data, ignore_index=True)

        # Filter out suspended bars (suspendFlag=0 means active, suspendFlag=1 means suspended)
        # This is critical for SHFE minute data where bars exist but trading was suspended
        # (e.g., night session before holidays)
        if 'suspendFlag' in combined.columns:
            before_count = len(combined)
            combined = combined[combined['suspendFlag'] == 0]
            filtered_count = before_count - len(combined)
            if filtered_count > 0:
                logger.info(
                    f"[DATA_PIPELINE] Filtered {filtered_count} suspended bars "
                    f"(suspendFlag=1), {len(combined)} active bars remaining"
                )

        return combined

    else:
        # Load day data: try sort_by_date.csv first, then raw Excel files
        # Check in instrument directory first
        source_csv = RAW_DATA_DIR / market / instrument_code / "sort_by_date.csv"
        if source_csv.exists():
            logger.info(f"[DATA_PIPELINE] Loading day data from {source_csv}")
            return pd.read_csv(source_csv)

        # Fallback: load from raw Excel files in day_data directory
        raw_data_dir = RAW_DATA_DIR / market / "day_data"
        if raw_data_dir.exists():
            logger.info(f"[DATA_PIPELINE] Loading day data from Excel files in {raw_data_dir}")
            extractor = _get_extractor(market, instrument, frequency)
            # Extract raw data but don't save (just loading for transformation)
            return extractor.extract_raw(input_dir=str(raw_data_dir), save=False)

        # Try raw_data as alternative directory name
        raw_data_dir = RAW_DATA_DIR / market / "raw_data"
        if raw_data_dir.exists():
            logger.info(f"[DATA_PIPELINE] Loading day data from Excel files in {raw_data_dir}")
            extractor = _get_extractor(market, instrument, frequency)
            return extractor.extract_raw(input_dir=str(raw_data_dir), save=False)

        logger.warning(f"[DATA_PIPELINE] No day data source found for {market}/{instrument}")
        return None


def _analyze_shfe_sessions(
    standardized_data: pd.DataFrame,
    output_path: Path,
    bar_size: str
) -> None:
    """
    Analyze SHFE session availability from standardized OHLCV data.

    This detects which sessions (night, morning, afternoon) were active
    for each trading date, handling irregular session availability due
    to holidays.

    Uses session definitions from: config/markets/shfe/phases.py

    Args:
        standardized_data: Standardized OHLCV data with session_phase and trading_date
        output_path: Directory to save session availability file
        bar_size: Bar size string (e.g., "5m", "15m")
    """
    # Parse bar size to minutes
    bar_size_minutes = _parse_bar_size_minutes(bar_size)

    # Analyze sessions - pass bar_size for correct phase names (granular vs aggregated)
    analyzer = SHFESessionAnalyzer(bar_size_minutes=bar_size_minutes, bar_size=bar_size)
    session_info = analyzer.analyze_from_ohlcv(standardized_data)

    # Save session availability info
    analyzer.save_session_info(session_info, output_path)

    # Enhance calendar with session info if calendar exists
    calendar_file = output_path / "trading_calendar.csv"
    if calendar_file.exists():
        calendar_df = pd.read_csv(calendar_file)
        enhanced_calendar = analyzer.enhance_calendar(calendar_df, session_info)
        enhanced_calendar.to_csv(calendar_file, index=False)
        logger.info(f"[DATA_PIPELINE] Enhanced calendar with session availability: {calendar_file}")


def _parse_bar_size_minutes(bar_size: str) -> int:
    """
    Parse bar size string to minutes.

    Args:
        bar_size: Bar size string (e.g., "1m", "5m", "15m", "1h", "1d")

    Returns:
        Bar size in minutes
    """
    if bar_size.endswith('min'):
        return int(bar_size[:-3])
    elif bar_size.endswith('m'):
        return int(bar_size[:-1])
    elif bar_size.endswith('h'):
        return int(bar_size[:-1]) * 60
    elif bar_size.endswith('d'):
        return int(bar_size[:-1]) * 60 * 24
    else:
        raise ValueError(
            f"Cannot parse bar_size '{bar_size}' - expected format like '5m', '15min', '1h', or '1d'"
        )

