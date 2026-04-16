"""
Portfolio Deploy Configuration
==============================

Configuration management for multi-instrument portfolio trading.
Loads session/portfolio_deploy_config.json and provides typed access
to slot definitions, deploy settings, and account configuration.
"""

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .deploy_config import QMTAccountConfig

logger = logging.getLogger(__name__)


@dataclass
class StrategyStep:
    """A single step in the 'How It Works' strategy description."""
    title: str = ""
    desc: str = ""


@dataclass
class SlotDashboardConfig:
    """Dashboard display metadata for a slot — set once at promotion time."""
    strategy_name: str = ""
    strategy_type: str = ""
    display_market: str = ""
    display_frequency: str = ""
    live_since: str = ""
    backtest_metrics: Dict[str, float] = field(default_factory=dict)
    strategy_steps: List[StrategyStep] = field(default_factory=list)


@dataclass
class SlotConfig:
    """Configuration for a single trading slot."""
    slot_id: str
    strategy_id: str
    cluster: str
    version: str
    instrument: str
    instrument_code: str
    market: str
    frequency: str
    bar_size: str
    initial_capital: float
    strategy_code_dir: str
    trial_params_path: str
    enabled: bool = True
    dashboard: SlotDashboardConfig = field(default_factory=SlotDashboardConfig)


@dataclass
class DeploySettings:
    """Portfolio-level deploy settings."""
    max_portfolio_drawdown_pct: float = 20.0
    max_total_capital: float = 3000000.0
    night_market_schedule_hour: int = 20
    night_market_schedule_minute: int = 40
    day_only_schedule_hour: int = 14
    day_only_schedule_minute: int = 55
    misfire_grace_time: int = 3600
    portfolio_backtest_metrics: Dict[str, float] = field(default_factory=dict)


@dataclass
class AccountConfig:
    """Account configuration section from portfolio config.

    Supports trade_account + test_account with a use_test_account toggle,
    matching DeployConfig's dual-account pattern for single-instrument trading.
    """
    trade_account: Optional[QMTAccountConfig] = None
    test_account: Optional[QMTAccountConfig] = None
    use_test_account: bool = False


@dataclass
class PortfolioDeployConfig:
    """Complete portfolio deployment configuration."""
    output_bank_dir: str = "../output_bank"
    slots: List[SlotConfig] = field(default_factory=list)
    deploy: DeploySettings = field(default_factory=DeploySettings)
    account: AccountConfig = field(default_factory=AccountConfig)

    @classmethod
    def load(cls, config_path: str) -> 'PortfolioDeployConfig':
        """Load configuration from JSON file."""
        with open(config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        config = cls()
        config.output_bank_dir = data.get('output_bank_dir', '../output_bank')

        # Parse slots
        for slot_data in data.get('slots', []):
            # Extract nested dashboard config before passing to SlotConfig
            dashboard_data = slot_data.pop('dashboard', {})
            steps = [
                StrategyStep(title=s.get('title', ''), desc=s.get('desc', ''))
                for s in dashboard_data.get('strategy_steps', [])
            ]
            dashboard_cfg = SlotDashboardConfig(
                strategy_name=dashboard_data.get('strategy_name', ''),
                strategy_type=dashboard_data.get('strategy_type', ''),
                display_market=dashboard_data.get('display_market', ''),
                display_frequency=dashboard_data.get('display_frequency', ''),
                live_since=dashboard_data.get('live_since', ''),
                backtest_metrics=dashboard_data.get('backtest_metrics', {}),
                strategy_steps=steps,
            )
            config.slots.append(SlotConfig(**slot_data, dashboard=dashboard_cfg))

        # Parse deploy settings
        deploy_data = data.get('deploy', {})
        config.deploy = DeploySettings(**deploy_data)

        # Parse account
        account_data = data.get('account', {})
        account_cfg = AccountConfig()
        if 'trade_account' in account_data:
            account_cfg.trade_account = QMTAccountConfig(**account_data['trade_account'])
        if 'test_account' in account_data:
            account_cfg.test_account = QMTAccountConfig(**account_data['test_account'])
        account_cfg.use_test_account = account_data.get('use_test_account', False)
        config.account = account_cfg

        logger.info(
            f"Portfolio config loaded: {len(config.slots)} slots, "
            f"{len(config.get_enabled_slots())} enabled"
        )
        return config

    def get_enabled_slots(self) -> List[SlotConfig]:
        """Get only enabled slots."""
        return [s for s in self.slots if s.enabled]

    def get_slots_by_instrument_and_barsize(
        self,
    ) -> Dict[Tuple[str, str], List[SlotConfig]]:
        """Group enabled slots by (instrument_code, bar_size) tuple."""
        groups: Dict[Tuple[str, str], List[SlotConfig]] = defaultdict(list)
        for slot in self.get_enabled_slots():
            key = (slot.instrument_code, slot.bar_size)
            groups[key].append(slot)
        return dict(groups)

    def get_active_account(self) -> QMTAccountConfig:
        """Return QMTAccountConfig based on use_test_account toggle."""
        if self.account.use_test_account:
            if self.account.test_account is None:
                raise ValueError("use_test_account is True but no test_account configured")
            return self.account.test_account
        if self.account.trade_account is None:
            raise ValueError("use_test_account is False but no trade_account configured")
        return self.account.trade_account

    def get_slot(self, slot_id: str) -> Optional[SlotConfig]:
        """Get a specific slot by ID."""
        for slot in self.slots:
            if slot.slot_id == slot_id:
                return slot
        return None
