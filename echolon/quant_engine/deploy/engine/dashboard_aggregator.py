"""
Dashboard Aggregator
====================

Generates per-slot dashboards using generate_dashboard_data(),
enriches them with config metadata and capital state,
computes portfolio-level aggregates (equity curve, KPIs, backtest comparison),
and produces the full PortfolioDashboardPayload.

Output: deploy_data/dashboard_portfolio.json
"""

import json
import logging
import math
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from config.markets.factory import MarketFactory
from ..config.portfolio_deploy_config import PortfolioDeployConfig, SlotConfig
from .dashboard_data_generator import generate_dashboard_data

logger = logging.getLogger(__name__)


def generate_portfolio_dashboard(
    deploy_config: PortfolioDeployConfig,
    deploy_data_dir: str,
    portfolio_equity: float,
    portfolio_peak: float,
    slot_statuses: Dict[str, str],
    exclude_today: bool = True,
) -> Dict[str, Any]:
    """
    Generate portfolio dashboard with per-slot + aggregate views.

    Args:
        deploy_config: Loaded PortfolioDeployConfig with slot definitions.
        deploy_data_dir: Base deploy data directory.
        portfolio_equity: Current total portfolio equity.
        portfolio_peak: Peak portfolio equity (for DD calculation).
        slot_statuses: Mapping of slot_id -> "OK" / "ERROR".

    Returns:
        Full PortfolioDashboardPayload matching the migration schema.
    """
    enabled_slots = deploy_config.get_enabled_slots()
    slot_dashboards: List[Dict[str, Any]] = []

    for slot_config in sorted(enabled_slots, key=lambda s: s.slot_id):
        slot_id = slot_config.slot_id
        status = slot_statuses.get(slot_id, 'OK')
        strategy_state: Dict[str, Any] = {}

        # Generate runtime data (equity curve, position, kpis)
        try:
            slot_dir = os.path.join(deploy_data_dir, 'slots', slot_id)
            trading_data_dir = slot_dir
            state_path = os.path.join(slot_dir, 'strategy_state.json')
            strategy_state = _load_json(state_path) or {}

            # Resolve main contract from strategy state
            main_contract = strategy_state.get('position_symbol', '')

            dd = generate_dashboard_data(
                trading_data_dir=trading_data_dir,
                strategy_state_path=state_path,
                main_contract=main_contract,
                symbol=slot_config.instrument,
                contract_multiplier=_get_multiplier(slot_config),
            )
        except Exception as e:
            logger.warning(f"[{slot_id}] Dashboard generation failed: {e}")
            dd = {
                'updated_at': datetime.now().astimezone().isoformat(),
                'equity_curve': [],
                'position': None,
                'kpis': _empty_kpis(),
            }
            status = 'ERROR'

        # Enrich with config metadata + capital
        enriched = _enrich_slot_data(dd, slot_config, strategy_state, status)
        slot_dashboards.append(enriched)

    # Build portfolio aggregate
    total_initial_capital = sum(s.initial_capital for s in enabled_slots)

    # Use real equity from slot curves if available, else fallback
    if slot_dashboards:
        portfolio_equity_from_curves = sum(
            sd['capital']['equity'] for sd in slot_dashboards
            if sd['status'] == 'OK'
        )
        if portfolio_equity_from_curves > 0:
            portfolio_equity = portfolio_equity_from_curves

    portfolio_equity_curve = _build_portfolio_equity_curve(slot_dashboards)
    portfolio_kpis = _compute_portfolio_kpis(portfolio_equity_curve, slot_dashboards, exclude_today)
    portfolio_backtest = _build_portfolio_backtest_comparison(
        portfolio_kpis, deploy_config
    )

    dd_pct = 0.0
    if portfolio_peak > 0:
        dd_pct = round((portfolio_peak - portfolio_equity) / portfolio_peak * 100.0, 2)

    total_return_pct = 0.0
    if total_initial_capital > 0:
        total_return_pct = round(
            (portfolio_equity - total_initial_capital) / total_initial_capital * 100.0, 2
        )

    active_count = sum(1 for sd in slot_dashboards if sd['status'] == 'OK')
    errored_count = sum(1 for sd in slot_dashboards if sd['status'] == 'ERROR')

    payload = {
        'updated_at': datetime.now().astimezone().isoformat(),
        'portfolio': {
            'equity_curve': portfolio_equity_curve,
            'total_equity': round(portfolio_equity, 2),
            'total_initial_capital': round(total_initial_capital, 2),
            'total_return_pct': total_return_pct,
            'kpis': portfolio_kpis,
            'backtest_comparison': portfolio_backtest,
            'peak_equity': round(portfolio_peak, 2),
            'drawdown_pct': dd_pct,
            'active_slots': active_count,
            'errored_slots': errored_count,
            'total_slots': len(deploy_config.slots),
        },
        'slots': slot_dashboards,
    }

    return payload


def save_portfolio_dashboard(
    dashboard: Dict[str, Any],
    output_path: str,
) -> None:
    """Save portfolio dashboard to JSON."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(dashboard, f, indent=2, default=str)
    logger.info(f"Portfolio dashboard saved to {output_path}")


# =========================================================================
# Slot Enrichment
# =========================================================================

def _enrich_slot_data(
    slot_dashboard: Dict[str, Any],
    slot_config: SlotConfig,
    strategy_state: Dict[str, Any],
    status: str,
) -> Dict[str, Any]:
    """Add metadata, strategy info, backtest comparison, and capital to per-slot data."""
    capital_state = strategy_state.get('custom', {}).get('capital', {})
    db = slot_config.dashboard

    # Metadata from config (strategy_id excluded — not for public display)
    slot_dashboard['slot_id'] = slot_config.slot_id
    slot_dashboard['instrument'] = slot_config.instrument
    slot_dashboard['instrument_code'] = slot_config.instrument_code
    slot_dashboard['status'] = status

    # Strategy info from config (replaces hardcoded _build_strategy_info)
    slot_dashboard['strategy'] = {
        'name': db.strategy_name,
        'type': db.strategy_type,
        'market': db.display_market,
        'frequency': db.display_frequency,
        'live_since': db.live_since,
        'steps': [{'title': s.title, 'desc': s.desc} for s in db.strategy_steps],
    }

    # Backtest comparison from config
    bt = db.backtest_metrics
    live_kpis = slot_dashboard.get('kpis', {})
    slot_dashboard['backtest_comparison'] = {
        'sharpe_ratio': {
            'backtest': bt.get('sharpe_ratio', 0),
            'live': live_kpis.get('sharpe_ratio'),
        },
        'annual_return': {
            'backtest': bt.get('annual_return', 0),
            'live': live_kpis.get('annual_return'),
        },
        'max_drawdown': {
            'backtest': bt.get('max_drawdown', 0),
            'live': live_kpis.get('max_drawdown'),
        },
    }

    # Capital from strategy_state.json
    unrealized_pnl = 0.0
    if slot_dashboard.get('position'):
        unrealized_pnl = slot_dashboard['position'].get('unrealized_pnl', 0.0)

    equity = slot_config.initial_capital
    if slot_dashboard.get('equity_curve'):
        equity = slot_dashboard['equity_curve'][-1]['value']

    slot_dashboard['capital'] = {
        'initial': capital_state.get('initial_capital', slot_config.initial_capital),
        'equity': equity,
        'realized_pnl': capital_state.get('realized_pnl', 0.0),
        'unrealized_pnl': unrealized_pnl,
    }

    return slot_dashboard


# =========================================================================
# Portfolio Equity Curve
# =========================================================================

def _build_portfolio_equity_curve(
    slot_dashboards: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Sum per-slot equity curves aligned by date.

    For dates where a slot has no data point (started later or errored),
    use that slot's initial_capital as the value.
    """
    ok_slots = [sd for sd in slot_dashboards if sd.get('status') == 'OK']
    if not ok_slots:
        return []

    # Pre-build date→value maps once per slot (avoid O(dates*slots*curve) rebuild)
    slot_curves = []
    all_date_set: set = set()
    for sd in ok_slots:
        curve_map = {p['date']: p['value'] for p in sd.get('equity_curve', [])}
        slot_curves.append((curve_map, sd['capital']['initial']))
        all_date_set.update(curve_map.keys())

    all_dates = sorted(all_date_set)

    portfolio_curve = []
    for date in all_dates:
        total = 0.0
        for curve_map, initial in slot_curves:
            total += curve_map.get(date, initial)
        portfolio_curve.append({'date': date, 'value': round(total, 2)})

    return portfolio_curve


# =========================================================================
# Portfolio KPIs
# =========================================================================

def _compute_portfolio_kpis(
    portfolio_equity_curve: List[Dict[str, Any]],
    slot_dashboards: List[Dict[str, Any]],
    exclude_today: bool = True,
) -> Dict[str, Any]:
    """Compute portfolio KPIs from aggregate equity curve + per-slot trade stats.

    Applies 24h delay (excludes today's data point) for curve-derived KPIs
    unless exclude_today is False.
    """
    MIN_DAYS_SHARPE = 30
    MIN_DAYS_ANNUAL_RETURN = 20
    MIN_DAYS_MAX_DRAWDOWN = 10

    kpis: Dict[str, Any] = _empty_kpis()

    # Apply 24h delay — exclude today's data point
    if exclude_today:
        today_str = datetime.now().strftime('%Y-%m-%d')
        delayed_curve = [p for p in portfolio_equity_curve if p['date'] != today_str]
    else:
        delayed_curve = list(portfolio_equity_curve)
    values = [p['value'] for p in delayed_curve]

    if len(values) >= 2:
        n_days = len(values)

        # Max drawdown
        if n_days >= MIN_DAYS_MAX_DRAWDOWN:
            peak = values[0]
            max_dd = 0.0
            for v in values:
                if v > peak:
                    peak = v
                dd = (v - peak) / peak
                if dd < max_dd:
                    max_dd = dd
            kpis['max_drawdown'] = round(max_dd, 4)

        # Annual return
        if n_days >= MIN_DAYS_ANNUAL_RETURN:
            first_val = float(values[0])
            last_val = float(values[-1])
            if first_val > 0:
                total_return = last_val / first_val
                annualized = total_return ** (252.0 / n_days) - 1
                kpis['annual_return'] = round(annualized, 4)

        # Sharpe ratio
        if n_days >= MIN_DAYS_SHARPE:
            daily_returns = []
            for i in range(1, len(values)):
                if values[i - 1] > 0:
                    daily_returns.append(values[i] / values[i - 1] - 1)
            if daily_returns:
                mean_ret = sum(daily_returns) / len(daily_returns)
                variance = sum((r - mean_ret) ** 2 for r in daily_returns) / len(daily_returns)
                std_ret = math.sqrt(variance)
                if std_ret > 0:
                    kpis['sharpe_ratio'] = round(mean_ret / std_ret * math.sqrt(252), 2)

    # Trade-aggregated KPIs from per-slot values (OK slots only)
    ok_slots = [sd for sd in slot_dashboards if sd.get('status') == 'OK']
    for kpi_key in ['win_rate', 'profit_factor', 'avg_hold_days', 'trades_per_week']:
        slot_values = [
            sd['kpis'][kpi_key]
            for sd in ok_slots
            if sd.get('kpis', {}).get(kpi_key) is not None
        ]
        if not slot_values:
            kpis[kpi_key] = None
        elif kpi_key == 'trades_per_week':
            kpis[kpi_key] = round(sum(slot_values), 1)
        else:
            kpis[kpi_key] = round(sum(slot_values) / len(slot_values), 3)

    return kpis


# =========================================================================
# Portfolio Backtest Comparison
# =========================================================================

def _build_portfolio_backtest_comparison(
    portfolio_kpis: Dict[str, Any],
    deploy_config: PortfolioDeployConfig,
) -> Dict[str, Any]:
    """Combine config backtest metrics with live portfolio KPIs."""
    bt = deploy_config.deploy.portfolio_backtest_metrics
    return {
        'sharpe_ratio': {
            'backtest': bt.get('sharpe_ratio', 0),
            'live': portfolio_kpis.get('sharpe_ratio'),
        },
        'annual_return': {
            'backtest': bt.get('annual_return', 0),
            'live': portfolio_kpis.get('annual_return'),
        },
        'max_drawdown': {
            'backtest': bt.get('max_drawdown', 0),
            'live': portfolio_kpis.get('max_drawdown'),
        },
    }


# =========================================================================
# Helpers
# =========================================================================

def _empty_kpis() -> Dict[str, Any]:
    return {
        'sharpe_ratio': None,
        'annual_return': None,
        'max_drawdown': None,
        'win_rate': None,
        'profit_factor': None,
        'avg_hold_days': None,
        'trades_per_week': None,
    }


def _load_json(path: str) -> Optional[Dict[str, Any]]:
    """Load a JSON file, return None if not found."""
    if not path or not os.path.exists(path):
        return None
    with open(path, 'r') as f:
        return json.load(f)


def _get_multiplier(slot_config: SlotConfig) -> int:
    """Get contract multiplier from instrument specs via MarketFactory."""
    spec = MarketFactory.get_instrument(slot_config.market, slot_config.instrument_code)
    if spec:
        return int(spec.multiplier)
    logger.warning(
        f"[{slot_config.slot_id}] Unknown instrument {slot_config.market}/{slot_config.instrument_code}, "
        f"using default multiplier 5"
    )
    return 5


