"""
XtDataCenter Client
===================

Token-based data client using xtdatacenter (xtdc) for market data access.

This is a lightweight alternative to MiniQMTClient for data-only operations.
It connects to xuntou's remote data service via token authentication, without
requiring the miniQMT desktop client to be running.

Key difference from MiniQMTClient:
- MiniQMTClient: connects to local miniQMT desktop via xttrader + xtdata
- XtdcClient: connects to remote xuntou servers via xtdatacenter token + xtdata

Both expose the same data methods (get_market_data, extract_dataframe_from_data)
so they can be used interchangeably as the `client` parameter in run_data_pipeline().

Additionally provides download_main_contract_history() which requires the
token-based API (historymaincontract is not available via miniQMT).

Usage:
    client = XtdcClient()
    client.connect()
    # Use as drop-in replacement for MiniQMTClient in run_data_pipeline()
    client.disconnect()
"""

import datetime
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Union

import pandas as pd

logger = logging.getLogger(__name__)

# Default port for xtdatacenter listener
XTDC_DEFAULT_PORT = 58615


class XtdcClient:
    """
    Token-based xtdatacenter client for market data.

    Provides the same data interface as MiniQMTClient (get_market_data,
    extract_dataframe_from_data) so it can be passed to run_data_pipeline()
    via extractor.set_client().

    The xtdc listener (xtdc.init + xtdc.listen) is initialized once per
    process and kept alive. Only the xtdata client connection is
    opened/closed on each connect()/disconnect() cycle. This avoids
    port-conflict errors when the same long-running process (e.g.
    portfolio_runner with APScheduler) calls connect() on multiple days.
    """

    # Class-level flag: xtdc listener initialized once per process
    _listener_ready = False

    def __init__(self, port: int = XTDC_DEFAULT_PORT):
        self._port = port
        self._connected = False

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @classmethod
    def _ensure_listener(cls, port: int) -> None:
        """Initialize xtdc listener once per process.

        Subsequent calls are no-ops. The listener stays alive for the
        lifetime of the process so that daily xtdata reconnections can
        reuse the same port without conflict.
        """
        if cls._listener_ready:
            return

        from xtquant import xtdatacenter as xtdc

        token = os.environ.get(
            "XUNTOU_TOKEN",
            "322da8d9be7984b62a76249e8cf0e71067fb0612",
        )

        xtdc.set_token(token)
        xtdc.set_quote_time_mode_v2(True)

        addr_list = ['115.231.218.73:55310', '115.231.218.79:55310']
        xtdc.set_allow_optmize_address(addr_list)
        xtdc.set_index_mirror_enabled(True)
        xtdc.set_future_realtime_mode(True)
        xtdc.init(False)
        xtdc.listen(port=port)

        cls._listener_ready = True
        logger.info("[XTDC] Listener initialized on port %d", port)

    def connect(self) -> bool:
        """Connect to xuntou data service via xtdatacenter token.

        Returns:
            True if connection successful.
        """
        if self._connected:
            return True

        try:
            self._ensure_listener(self._port)

            from xtquant import xtdata
            xtdata.connect(port=self._port)

            self._connected = True
            logger.info("[XTDC] Connected on port %d", self._port)
            return True

        except ImportError:
            logger.error("[XTDC] xtquant library not installed")
            raise
        except Exception as e:
            logger.error("[XTDC] Connection failed: %s", e)
            return False

    def disconnect(self) -> None:
        """Disconnect xtdata client. The xtdc listener stays alive."""
        if not self._connected:
            return
        try:
            from xtquant import xtdata
            xtdata.disconnect()
            self._connected = False
            logger.info("[XTDC] Disconnected")
        except Exception as e:
            logger.warning("[XTDC] Disconnect failed: %s", e)

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # Main contract history (token-only API)
    # ------------------------------------------------------------------

    def download_main_contract_history(
        self,
        futures_code: str,
        xuntou_code: str,
        output_dir: Optional[str] = None,
    ) -> pd.DataFrame:
        """Download main contract history via xtdatacenter.

        This data is only available through the token-based API,
        not through the miniQMT desktop connection.

        Args:
            futures_code: Futures product code (e.g. 'al', 'cu').
            xuntou_code: Exchange code (e.g. 'SF').
            output_dir: If provided, saves main_contract.csv there.

        Returns:
            DataFrame with columns [date, main_contract].
        """
        from xtquant import xtdata

        symbol = f"{futures_code}00.{xuntou_code}"
        period = "historymaincontract"

        logger.info("[XTDC] Downloading main contract history for %s", symbol)

        xtdata.download_history_data(symbol, period, '', '')
        data_dict = xtdata.get_market_data_ex([], [symbol], period)

        if not data_dict or symbol not in data_dict:
            logger.warning("[XTDC] No main contract data for %s", symbol)
            return pd.DataFrame()

        df = data_dict[symbol].copy()

        df['date'] = pd.to_datetime(df['time'], unit='ms')
        df['date'] = df['date'].dt.strftime('%Y-%m-%d')

        df_filtered = df[['date', '期货统一规则代码']].copy()
        df_filtered.rename(
            columns={'期货统一规则代码': 'main_contract'}, inplace=True,
        )

        if output_dir:
            out_path = Path(output_dir)
            out_path.mkdir(parents=True, exist_ok=True)
            csv_path = out_path / "main_contract.csv"
            df_filtered.to_csv(csv_path, index=False, encoding='utf-8-sig')
            logger.info("[XTDC] Main contract saved: %s (%d entries)", csv_path, len(df_filtered))

        return df_filtered

    def get_stock_list_in_sector(self, sector: str) -> List[str]:
        """Get all stock/futures codes in a sector.

        Args:
            sector: Sector code (e.g. 'SF' for SHFE futures).

        Returns:
            List of contract codes (e.g. ['al2507.SF', ...]).
        """
        from xtquant import xtdata

        try:
            result = xtdata.get_stock_list_in_sector(sector)
            return result if result else []
        except Exception as exc:
            logger.error("[XTDC] Failed to get stock list in sector %s: %s", sector, exc)
            return []

    # ------------------------------------------------------------------
    # Market data (same interface as MiniQMTClient)
    # ------------------------------------------------------------------

    def download_history_data(
        self,
        symbols: Union[str, List[str]],
        period: str = "1d",
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        count: int = -1,
    ) -> bool:
        """Download historical market data via xtdata.

        Same interface as MiniQMTClient.download_history_data().
        """
        from xtquant import xtdata

        try:
            if isinstance(symbols, str):
                symbols = [symbols]

            logger.info(
                "Downloading historical data for %s, period: %s", symbols, period
            )

            for symbol in symbols:
                result = xtdata.download_history_data(
                    stock_code=symbol,
                    period=period,
                    start_time=start_time,
                    end_time=end_time,
                )
                logger.info("Download result for %s: %s", symbol, result)

            logger.info("Historical data download completed")
            return True

        except Exception as exc:
            logger.error("Failed to download historical data: %s", exc)
            return False

    def get_market_data(
        self,
        symbols: Union[str, List[str]],
        period: str = "1d",
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        fields: Optional[List[str]] = None,
    ) -> Optional[Dict]:
        """Get market data. Same interface as MiniQMTClient.get_market_data()."""
        from xtquant import xtdata

        try:
            if isinstance(symbols, str):
                symbols = [symbols]

            if not end_time:
                end_time = datetime.datetime.now().strftime("%Y%m%d")

            self.download_history_data(symbols, period, start_time, end_time)

            market_data = xtdata.get_market_data_ex(
                field_list=[],
                stock_list=symbols,
                period=period,
                start_time=start_time,
                end_time=end_time,
            )

            logger.info("Retrieved market data for %s", symbols)
            return market_data

        except Exception as exc:
            logger.error("Failed to get market data: %s", exc)
            return None

    def extract_dataframe_from_data(
        self,
        market_data: Dict,
        symbol: str,
    ) -> Optional[pd.DataFrame]:
        """Extract DataFrame from market data dict.

        Same interface as MiniQMTClient.extract_dataframe_from_data().
        """
        if not market_data or not isinstance(market_data, dict):
            logger.error("Invalid market data format")
            return None

        if symbol not in market_data:
            logger.error(
                "Symbol %s not found in data. Available: %s",
                symbol, list(market_data.keys()),
            )
            return None

        symbol_data = market_data[symbol]

        required_fields = ["open", "high", "low", "close", "volume"]
        if not all(field in symbol_data for field in required_fields):
            logger.error(
                "Missing required fields for %s. Available: %s",
                symbol, list(symbol_data.keys()),
            )
            return None

        try:
            timestamps = list(symbol_data["close"].keys())
            if not timestamps:
                logger.error("No timestamp data found for %s", symbol)
                return None

            dates = pd.to_datetime(timestamps, format="%Y%m%d")

            df_data = {}
            for field in required_fields:
                field_data = symbol_data[field]
                values = [field_data.get(ts, None) for ts in timestamps]
                df_data[field] = values

            df = pd.DataFrame(df_data, index=dates)

            for col in ["open", "high", "low", "close"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce")

            df = df.dropna()

            if df.empty:
                logger.error("No valid data after cleaning for %s", symbol)
                return None

            df = df.sort_index()
            logger.info(
                "Extracted DataFrame for %s: %d bars from %s to %s",
                symbol, len(df), df.index[0], df.index[-1],
            )
            return df

        except Exception as exc:
            logger.error("Failed to extract DataFrame for %s: %s", symbol, exc)
            return None
