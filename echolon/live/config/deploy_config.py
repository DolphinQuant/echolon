"""
Deploy Configuration
====================

Configuration management for live trading deployment.
Ported from QTS_deploy/config/qmt_config.py + data_config.py.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, Optional


@dataclass
class QMTAccountConfig:
    """QMT account configuration."""
    qmt_path: str
    account_id: str
    account_type: str = "FUTURE"


@dataclass
class DeployConfig:
    """
    Complete deployment configuration.

    Consolidates account, data paths, scheduling, indicators,
    and execution settings into a single config object.
    """
    # Account
    trade_account: Optional[QMTAccountConfig] = None
    test_account: Optional[QMTAccountConfig] = None
    use_test_account: bool = True

    # Data paths
    indicator_dir: str = ""
    strategy_data_dir: str = ""
    trading_data_dir: str = ""

    # Scheduling
    night_market_schedule_hour: int = 20
    night_market_schedule_minute: int = 40
    day_only_schedule_hour: int = 14
    day_only_schedule_minute: int = 55
    misfire_grace_time: int = 3600

    # Trial params path
    trial_params_path: Optional[str] = None

    @property
    def active_account(self) -> QMTAccountConfig:
        """Get the active account config based on use_test_account flag."""
        if self.use_test_account:
            return self.test_account
        return self.trade_account

    @classmethod
    def load(cls, config_path: str) -> 'DeployConfig':
        """
        Load config from JSON file.

        Args:
            config_path: Path to JSON config file

        Returns:
            DeployConfig instance
        """
        with open(config_path, 'r') as f:
            data = json.load(f)

        config = cls()

        # Account configs
        if 'trade_account' in data:
            config.trade_account = QMTAccountConfig(**data['trade_account'])
        if 'test_account' in data:
            config.test_account = QMTAccountConfig(**data['test_account'])
        config.use_test_account = data.get('use_test_account', True)

        # Data paths
        config.indicator_dir = data.get('indicator_dir', config.indicator_dir)
        config.strategy_data_dir = data.get('strategy_data_dir', config.strategy_data_dir)
        config.trading_data_dir = data.get('trading_data_dir', config.trading_data_dir)

        # Scheduling
        config.night_market_schedule_hour = data.get('night_market_schedule_hour', 20)
        config.night_market_schedule_minute = data.get('night_market_schedule_minute', 40)
        config.day_only_schedule_hour = data.get('day_only_schedule_hour', 14)
        config.day_only_schedule_minute = data.get('day_only_schedule_minute', 55)
        config.misfire_grace_time = data.get('misfire_grace_time', 3600)

        # Trial params
        config.trial_params_path = data.get('trial_params_path')

        # Resolve empty paths from centralized config
        config.resolve_paths()

        return config

    @classmethod
    def from_paths(
        cls,
        deploy_data_dir: str,
        trade_account: Optional[QMTAccountConfig] = None,
        test_account: Optional[QMTAccountConfig] = None,
        use_test_account: bool = True,
    ) -> 'DeployConfig':
        """
        Create config from a base data directory.

        Args:
            deploy_data_dir: Base directory for deployment data
            trade_account: Trade account config
            test_account: Test account config
            use_test_account: Whether to use test account
        """
        config = cls()
        config.trade_account = trade_account
        config.test_account = test_account
        config.use_test_account = use_test_account
        config.indicator_dir = os.path.join(deploy_data_dir, "indicators")
        config.strategy_data_dir = os.path.join(deploy_data_dir, "strategy_data")
        config.trading_data_dir = os.path.join(deploy_data_dir, "trading_data")
        return config

    def resolve_paths(self) -> None:
        """
        Fill in empty data paths from centralized config (config.settings).

        Called automatically after load(). Only overrides fields that are
        still empty strings.
        """
        from echolon.config.settings import INDICATORS_BACKTEST_DIR, WORKSPACE_DIR

        if not self.indicator_dir:
            self.indicator_dir = str(INDICATORS_BACKTEST_DIR)

        if not self.strategy_data_dir:
            self.strategy_data_dir = str(WORKSPACE_DIR / "current" / "strategy")

        if not self.trading_data_dir:
            self.trading_data_dir = str(WORKSPACE_DIR / "deploy")

        # Resolve trial_params_path from best params file if not set
        if not self.trial_params_path:
            from echolon.config.settings import BEST_PARAMS_FILE
            if os.path.exists(BEST_PARAMS_FILE):
                self.trial_params_path = BEST_PARAMS_FILE

    @property
    def calendar_path(self) -> str:
        """Path to the static deploy trading calendar CSV."""
        return str(
            Path(__file__).parent / "trading_calendar.csv"
        )
