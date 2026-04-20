"""
SHFE Contract Rules
===================

Contract expiry and rollover logic for SHFE futures.

Functions:
- parse_contract(contract_str): Parse "al2403" into (symbol, year, month)
- get_expiry_date(contract_str): Calculate expiry date for contract
- get_rollover_date(contract_str): Get date when position should roll
- is_delivery_month(contract_str, check_date): Check if in delivery month

SHFE expiry rules:
- Delivery month: The month in the contract name (al2403 → March 2024)
- Last trading day: 15th of delivery month (or prior business day)
- Position must close: By last trading day of month BEFORE delivery month
- Example: al2403 position must close by end of February 2024

Rollover strategy:
- Monitor current contract's proximity to expiry
- Signal rollover when position should move to next main contract
- Coordinate with trading_calendar.py for valid trading days
"""

import re
from datetime import date
from typing import Dict, Optional, Tuple
from pathlib import Path

import pandas as pd

from .trading_calendar import TradingCalendar, get_last_trading_day_of_month

# Cache for main contract data to avoid repeated file reads.
# Keyed by (symbol_lower, str(resolved raw_data_dir)) so different injected
# raw-data directories don't collide on re-entry.
_main_contract_cache: Dict[Tuple[str, str], pd.DataFrame] = {}


def parse_contract(contract_str: str) -> Tuple[str, int, int]:
    """
    Parse contract code into components.

    Args:
        contract_str: Contract code (e.g., 'al2403', 'cu2405')

    Returns:
        Tuple of (symbol, year, month)
        - symbol: Product code (e.g., 'al', 'cu')
        - year: Full year (e.g., 2024)
        - month: Month (1-12)

    Raises:
        ValueError: If contract string is invalid

    Examples:
        >>> parse_contract('al2403')
        ('al', 2024, 3)
        >>> parse_contract('cu2512')
        ('cu', 2025, 12)
    """
    # Pattern: letters followed by 4 digits (YYMM)
    match = re.match(r'^([a-zA-Z]+)(\d{4})$', contract_str.strip())
    if not match:
        raise ValueError(f"Invalid contract format: {contract_str}")

    symbol = match.group(1).lower()
    yymm = match.group(2)

    year_2digit = int(yymm[:2])
    month = int(yymm[2:4])

    # Validate month
    if month < 1 or month > 12:
        raise ValueError(f"Invalid month in contract: {contract_str}")

    # Convert 2-digit year to 4-digit year
    # Assume years 00-50 are 2000-2050, years 51-99 are 1951-1999
    if year_2digit <= 50:
        year = 2000 + year_2digit
    else:
        year = 1900 + year_2digit

    return symbol, year, month


def format_contract(symbol: str, year: int, month: int) -> str:
    """
    Format contract components into contract code.

    Args:
        symbol: Product code (e.g., 'al', 'cu')
        year: Year (2-digit or 4-digit)
        month: Month (1-12)

    Returns:
        Contract code (e.g., 'al2403')

    Examples:
        >>> format_contract('al', 2024, 3)
        'al2403'
        >>> format_contract('cu', 25, 12)
        'cu2512'
    """
    # Convert to 2-digit year if needed
    if year >= 2000:
        year_2digit = year - 2000
    elif year >= 1900:
        year_2digit = year - 1900
    else:
        year_2digit = year

    return f"{symbol.lower()}{year_2digit:02d}{month:02d}"


def get_delivery_month(contract_str: str) -> Tuple[int, int]:
    """
    Get the delivery month (year, month) for a contract.

    The delivery month is the month specified in the contract code.

    Args:
        contract_str: Contract code (e.g., 'al2403')

    Returns:
        Tuple of (year, month) for delivery

    Examples:
        >>> get_delivery_month('al2403')
        (2024, 3)
    """
    _, year, month = parse_contract(contract_str)
    return year, month


def get_expiry_date(
    contract_str: str,
    calendar: Optional[TradingCalendar] = None
) -> date:
    """
    Calculate the expiry date for a contract.

    SHFE rule: Position must be closed by the last trading day
    of the month BEFORE the delivery month.

    Args:
        contract_str: Contract code (e.g., 'al2403')
        calendar: Optional trading calendar for accurate date calculation

    Returns:
        Expiry date (last day position can be held)

    Examples:
        >>> get_expiry_date('al2403')  # March 2024 delivery
        date(2024, 2, 29)  # Last trading day of February 2024
    """
    _, year, month = parse_contract(contract_str)

    # Get the month before delivery month
    if month == 1:
        expiry_year = year - 1
        expiry_month = 12
    else:
        expiry_year = year
        expiry_month = month - 1

    # Get last trading day of expiry month
    return get_last_trading_day_of_month(expiry_year, expiry_month, calendar)


def get_rollover_signal_date(
    contract_str: str,
    days_before_expiry: int = 2,
    calendar: Optional[TradingCalendar] = None
) -> date:
    """
    Get the date when rollover should be signaled.

    This is typically 1-2 trading days before expiry to ensure
    the position can be rolled smoothly.

    Args:
        contract_str: Contract code
        days_before_expiry: Trading days before expiry to signal
        calendar: Optional trading calendar

    Returns:
        Date to signal rollover

    Examples:
        >>> get_rollover_signal_date('al2403', days_before_expiry=2)
        date(2024, 2, 27)  # 2 trading days before Feb 29
    """
    expiry_date = get_expiry_date(contract_str, calendar)

    # Walk back trading days
    signal_date = expiry_date
    if calendar:
        for _ in range(days_before_expiry):
            signal_date = calendar.get_previous_trading_day(signal_date)
    else:
        # Fallback: simple day subtraction (may land on weekend)
        from .trading_calendar import get_previous_trading_day
        for _ in range(days_before_expiry):
            signal_date = get_previous_trading_day(signal_date, calendar)

    return signal_date


def _load_main_contract_data(
    symbol: str,
    raw_data_dir: Optional[Path] = None,
) -> pd.DataFrame:
    """
    Load main contract data from CSV file.

    Args:
        symbol: Product symbol (e.g., 'al', 'cu', 'rb')
        raw_data_dir: Optional base raw-data directory. When None, falls back
            to PathsConfig rooted at PROJECT_ROOT.

    Returns:
        DataFrame with 'date' and 'main_contract' columns

    Raises:
        FileNotFoundError: If main_contract.csv doesn't exist for symbol
    """
    global _main_contract_cache

    symbol_lower = symbol.lower()

    if raw_data_dir is None:
        from echolon.config.paths_config import PathsConfig
        from echolon.config.settings import PROJECT_ROOT
        raw_data_dir = PathsConfig.from_project_root(PROJECT_ROOT).raw_data_dir
    raw_data_dir = Path(raw_data_dir).resolve()

    cache_key = (symbol_lower, str(raw_data_dir))
    if cache_key in _main_contract_cache:
        return _main_contract_cache[cache_key]

    csv_path = raw_data_dir / "SHFE" / symbol_lower / "main_contract.csv"
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Main contract data not found for {symbol}: {csv_path}"
        )

    df = pd.read_csv(csv_path)
    df['date'] = pd.to_datetime(df['date']).dt.date
    df = df.sort_values('date').reset_index(drop=True)

    _main_contract_cache[cache_key] = df
    return df


def get_main_contract(
    trading_date: date,
    symbol: str,
    raw_data_dir: Optional[Path] = None,
) -> str:
    """
    Get the main contract code for a given trading date.

    Looks up the main contract from the main_contract.csv file, which contains
    the actual main contract determined by trading volume/open interest.

    Args:
        trading_date: The trading date
        symbol: Product symbol (e.g., 'al', 'cu', 'rb')
        raw_data_dir: Optional base raw-data directory. When None, falls back
            to PathsConfig rooted at PROJECT_ROOT.

    Returns:
        Main contract code (e.g., 'al2403', 'rb2410')

    Raises:
        FileNotFoundError: If main_contract.csv doesn't exist
        ValueError: If no main contract data available for the date

    Examples:
        >>> get_main_contract(date(2024, 1, 15), 'al')
        'al2403'
        >>> get_main_contract(date(2024, 9, 15), 'rb')
        'rb2501'  # rb has different rollover rules than al/cu
    """
    df = _load_main_contract_data(symbol, raw_data_dir=raw_data_dir)

    # Find the most recent entry on or before trading_date
    mask = df['date'] <= trading_date
    if not mask.any():
        raise ValueError(
            f"No main contract data available for {symbol} on or before {trading_date}. "
            f"Earliest data: {df['date'].min()}"
        )

    # Get the last row where date <= trading_date
    idx = df.loc[mask, 'date'].idxmax()
    main_contract_raw = df.loc[idx, 'main_contract']

    # Remove exchange suffix (e.g., '.SF') if present
    if '.' in main_contract_raw:
        main_contract = main_contract_raw.split('.')[0]
    else:
        main_contract = main_contract_raw

    return main_contract.lower()



# from dateutil.relativedelta import relativedelta
# def get_main_contract(trading_date: date, symbol: str = "aluminum"):
#     """
#     Get the main futures contract code for a given date.

#     Rule: Main contract is two months ahead of given date's month.
#     Format: {futures_code} + YYMM (without .SF extension for file lookup)

#     Parameters
#     ----------
#     date : datetime
#         The trading date for which to determine the main contract
#     futures : str
#         Futures variety (e.g., "aluminum", "copper")

#     Returns
#     -------
#     str
#         Main contract code (e.g., 'al2508' for aluminum, 'cu2508' for copper)

#     Examples
#     --------
#     If given date is June 2025 (06):
#     - aluminum: main contract will be 'al2508' (August 2025)
#     - copper: main contract will be 'cu2508' (August 2025)
#     """

#     # Add 2 months to the given date
#     main_contract_date = trading_date + relativedelta(months=2)

#     # Extract year (last 2 digits) and month (2 digits)
#     year_suffix = str(main_contract_date.year)[-2:]  # Last 2 digits of year
#     month_str = f"{main_contract_date.month:02d}"    # Month with leading zero if needed

#     # Format as contract: {futures_code} + YYMM (no .SF extension for file lookup)
#     main_contract = f"{symbol}{year_suffix}{month_str}"

#     return main_contract







def is_delivery_month(contract_str: str, check_date: date) -> bool:
    """
    Check if the given date is in the contract's delivery month.

    Args:
        contract_str: Contract code
        check_date: Date to check

    Returns:
        True if check_date is in the delivery month

    Examples:
        >>> is_delivery_month('al2403', date(2024, 3, 15))
        True
        >>> is_delivery_month('al2403', date(2024, 2, 28))
        False
    """
    delivery_year, delivery_month = get_delivery_month(contract_str)
    return check_date.year == delivery_year and check_date.month == delivery_month


def is_approaching_expiry(
    contract_str: str,
    check_date: date,
    days_threshold: int = 5,
    calendar: Optional[TradingCalendar] = None
) -> bool:
    """
    Check if contract is approaching expiry.

    Args:
        contract_str: Contract code
        check_date: Current date
        days_threshold: Number of days to consider "approaching"
        calendar: Optional trading calendar

    Returns:
        True if within threshold of expiry

    Examples:
        >>> is_approaching_expiry('al2403', date(2024, 2, 25), days_threshold=5)
        True  # If expiry is Feb 29
    """
    return days_until_expiry(contract_str, check_date, calendar) <= days_threshold


def days_until_expiry(
    contract_str: str,
    from_date: date,
    calendar: Optional[TradingCalendar] = None
) -> int:
    """
    Calculate calendar days until contract expiry.

    Args:
        contract_str: Contract code
        from_date: Starting date
        calendar: Optional trading calendar

    Returns:
        Number of calendar days until expiry (negative if past expiry)

    Examples:
        >>> days_until_expiry('al2403', date(2024, 2, 20))
        9  # If expiry is Feb 29
    """
    expiry_date = get_expiry_date(contract_str, calendar)
    return (expiry_date - from_date).days


def trading_days_until_expiry(
    contract_str: str,
    from_date: date,
    calendar: TradingCalendar
) -> int:
    """
    Calculate trading days until contract expiry.

    Args:
        contract_str: Contract code
        from_date: Starting date
        calendar: Trading calendar (required)

    Returns:
        Number of trading days until expiry
    """
    expiry_date = get_expiry_date(contract_str, calendar)
    return calendar.count_trading_days_between(from_date, expiry_date, inclusive=False)


def should_rollover(
    contract_str: str,
    check_date: date,
    position_size: int,
    calendar: Optional[TradingCalendar] = None,
    days_before_expiry: int = 2
) -> bool:
    """
    Determine if a position should be rolled over.

    Args:
        contract_str: Current contract code
        check_date: Current date
        position_size: Current position size (0 = no position)
        calendar: Optional trading calendar
        days_before_expiry: Days before expiry to signal rollover

    Returns:
        True if position should be rolled

    Examples:
        >>> should_rollover('al2403', date(2024, 2, 27), 10)
        True  # If signal date is Feb 27
    """
    # No position = no need to roll
    if position_size == 0:
        return False

    signal_date = get_rollover_signal_date(contract_str, days_before_expiry, calendar)
    return check_date >= signal_date


def get_rollover_target(
    current_contract: str,
    check_date: date,
    position_size: int,
    calendar: Optional[TradingCalendar] = None,
    raw_data_dir: Optional[Path] = None,
) -> Optional[str]:
    """
    Get the target contract for rollover.

    Args:
        current_contract: Current contract code
        check_date: Current date
        position_size: Current position size
        calendar: Optional trading calendar
        raw_data_dir: Optional base raw-data directory forwarded to
            get_main_contract. When None, falls back to PathsConfig rooted at
            PROJECT_ROOT.

    Returns:
        Target contract code, or None if no rollover needed

    Examples:
        >>> get_rollover_target('al2403', date(2024, 2, 27), 10)
        'al2404'  # If rollover is needed
    """
    if not should_rollover(current_contract, check_date, position_size, calendar):
        return None

    # Get the main contract for current date (which would be the next contract)
    symbol, _, _ = parse_contract(current_contract)
    return get_main_contract(check_date, symbol, raw_data_dir=raw_data_dir)
