"""
Base Extractor Interface
========================

Extractors are responsible for retrieving raw market data from sources.

Separation of Concerns:
- Extractors: ONLY retrieve raw data from files/APIs
- Transformers: Process and standardize the data
- Loaders: Provide data access to consumers

Note: split_by_contract and generate_trading_calendar are provided as
convenience methods that delegate to transformer classes. Subclasses
can override if special handling is needed.
"""
from abc import ABC, abstractmethod
from typing import Optional, List
import pandas as pd


class BaseExtractor(ABC):
    """
    Abstract base class for market data extractors.

    Extractors should focus on data retrieval only.
    Transformation is handled by transformer classes.
    """

    def __init__(self, market: str, asset: str):
        """
        Initialize extractor.

        Args:
            market: Market code (e.g., "SHFE", "CME")
            asset: Asset name (e.g., "aluminum", "copper")
        """
        self.market = market
        self.asset = asset

    @abstractmethod
    def extract_raw(
        self,
        input_dir: Optional[str] = None,
        output_dir: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        save: bool = True
    ) -> pd.DataFrame:
        """
        Extract raw market data from source files.

        This is the core extractor responsibility - getting raw data
        from exchange files, APIs, or other sources.

        Args:
            input_dir: Directory containing raw source files
            output_dir: Directory to save extracted data
            start_date: Optional start date filter (YYYY-MM-DD)
            end_date: Optional end date filter (YYYY-MM-DD)
            save: Whether to save extracted data to output_dir (default True)

        Returns:
            DataFrame with extracted OHLCV data
        """
        pass

    def split_by_contract(
        self,
        data: pd.DataFrame = None,
        output_dir: Optional[str] = None
    ) -> List[str]:
        """
        Split extracted data by contract using ContractSplitter transformer.

        Args:
            data: Extracted OHLCV data
            output_dir: Directory to save per-contract files

        Returns:
            List of contract names that were saved
        """
        from ..transformers.contract_splitter import ContractSplitter

        if data is None or data.empty:
            return []

        splitter = ContractSplitter(output_dir=output_dir)
        return splitter.split(data)

    def generate_trading_calendar(
        self,
        data: pd.DataFrame = None,
        output_dir: Optional[str] = None,
        start_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Generate trading calendar using CalendarGenerator transformer.

        Args:
            data: Extracted OHLCV data
            output_dir: Directory to save calendar
            start_date: Optional start date filter

        Returns:
            DataFrame with trading dates
        """
        from ..transformers.calendar_generator import CalendarGenerator

        if data is None or data.empty:
            return pd.DataFrame()

        calendar_gen = CalendarGenerator(output_dir=output_dir)
        return calendar_gen.generate(df=data, start_date=start_date)
