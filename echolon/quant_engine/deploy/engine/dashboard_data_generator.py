"""
Dashboard Data Generator
========================

Reads trading data from workspace CSV files and strategy state,
computes KPIs, and produces per-slot dashboard data for the aggregator.

Data sources:
- trading_data_{symbol}.csv     → equity curve, current position
- trade_executions_{symbol}.csv → win rate, profit factor, avg hold days
- strategy_state.json           → bars in position (hold days)
"""

import json
import os
import math
import logging
from datetime import datetime
from typing import Dict, Any, Optional

import pandas as pd

from ..config.logging_config import get_deploy_logger

logger = get_deploy_logger(__name__)


# =========================================================================
# Public API
# =========================================================================

def generate_dashboard_data(
    trading_data_dir: str,
    strategy_state_path: str,
    main_contract: str,
    symbol: str = 'aluminum',
    contract_multiplier: int = 5,
) -> Dict[str, Any]:
    """
    Generate per-slot dashboard data from workspace files.

    Strategy info, backtest comparison, and capital enrichment are handled
    by the DashboardAggregator using portfolio_deploy_config.json.

    Args:
        trading_data_dir: Directory containing trading CSVs (workspace/deploy/)
        strategy_state_path: Path to strategy_state.json
        main_contract: Current main contract (e.g. "al2604.SF")
        symbol: Instrument name used in CSV filenames
        contract_multiplier: Futures contract multiplier (aluminum = 5)

    Returns:
        Dictionary with: updated_at, equity_curve, position, kpis
    """
    # Load raw data
    trading_data = _load_trading_data(trading_data_dir, symbol)
    executions = _load_trade_executions(trading_data_dir, symbol)
    strategy_state = _load_json(strategy_state_path)

    # All public-facing data is 24h delayed: exclude today's rows so the
    # dashboard reflects yesterday's close, not today's in-progress cycle.
    delayed_data = _exclude_today_rows(trading_data)
    delayed_executions = _exclude_today_rows(executions)

    equity_curve = _build_equity_curve(delayed_data)
    position = _build_position(delayed_data, strategy_state, main_contract, contract_multiplier)
    last_trade = _build_last_trade(delayed_data, main_contract)
    kpis = _compute_kpis(delayed_data, delayed_executions)

    dashboard_data = {
        'updated_at': datetime.now().astimezone().isoformat(),
        'equity_curve': equity_curve,
        'position': position,
        'last_trade': last_trade,
        'kpis': kpis,
    }

    logger.info(
        f"Dashboard data generated: {len(equity_curve)} equity points, "
        f"position={'FLAT' if position is None else position['direction']}, "
        f"last_trade={last_trade['action'] if last_trade else 'none'}"
    )
    return dashboard_data


def save_dashboard_data(dashboard_data: Dict[str, Any], output_path: str) -> None:
    """Save dashboard data to JSON file."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(dashboard_data, f, indent=2)
    logger.info(f"Dashboard data saved to {output_path}")


# =========================================================================
# Data Loading
# =========================================================================

def _load_trading_data(trading_data_dir: str, symbol: str) -> Optional[pd.DataFrame]:
    """Load trading_data_{symbol}.csv."""
    path = os.path.join(trading_data_dir, f'trading_data_{symbol}.csv')
    if not os.path.exists(path):
        logger.warning(f"Trading data not found: {path}")
        return None
    df = pd.read_csv(path)
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp')
    return df


def _load_trade_executions(trading_data_dir: str, symbol: str) -> Optional[pd.DataFrame]:
    """Load trade_executions_{symbol}.csv."""
    path = os.path.join(trading_data_dir, f'trade_executions_{symbol}.csv')
    if not os.path.exists(path):
        logger.warning(f"Trade executions not found: {path}")
        return None
    df = pd.read_csv(path)
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp')
    return df


def _load_json(path: str) -> Optional[Dict[str, Any]]:
    """Load a JSON file, return None if not found."""
    if not path or not os.path.exists(path):
        logger.warning(f"JSON file not found: {path}")
        return None
    with open(path, 'r') as f:
        return json.load(f)


# =========================================================================
# 24h Delay
# =========================================================================

def _exclude_today_rows(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    """
    Exclude rows whose timestamp matches today's date to enforce 24h public delay.

    The generator runs immediately after today's trading cycle, so today's
    rows contain current position and equity. Filtering by date (instead of
    blindly dropping the last row) is correct because some DataFrames like
    trade_executions may not have any row from today.
    """
    if df is None or df.empty:
        return df
    if 'timestamp' not in df.columns:
        return df
    today = datetime.now().date()
    mask = df['timestamp'].dt.date != today
    filtered = df.loc[mask]
    return filtered if not filtered.empty else df.iloc[:0].copy()


# =========================================================================
# Equity Curve
# =========================================================================

def _build_equity_curve(trading_data: Optional[pd.DataFrame]) -> list:
    """Extract (date, value) pairs from trading data snapshots."""
    if trading_data is None or trading_data.empty:
        return []

    points = []
    for _, row in trading_data.iterrows():
        date_str = row['timestamp'].strftime('%Y-%m-%d') if hasattr(row['timestamp'], 'strftime') else str(row['timestamp'])[:10]
        points.append({
            'date': date_str,
            'value': round(float(row['total_account_value']), 2),
        })
    return points


# =========================================================================
# Position
# =========================================================================

def _build_position(
    trading_data: Optional[pd.DataFrame],
    strategy_state: Optional[Dict[str, Any]],
    main_contract: str,
    contract_multiplier: int,
) -> Optional[Dict[str, Any]]:
    """Build current position info from latest trading data row + strategy state."""
    if trading_data is None or trading_data.empty:
        return None

    latest = trading_data.iloc[-1]
    size = float(latest.get('current_position_size', 0))

    if size == 0:
        return None

    # Read direction directly from CSV column, fall back to scanning for old data
    direction = 'LONG'
    if 'position_direction' in latest.index and latest.get('position_direction'):
        direction = str(latest['position_direction']).upper()
    else:
        # Fallback for old CSV data without position_direction column
        for idx in range(len(trading_data) - 1, -1, -1):
            action = str(trading_data.iloc[idx].get('last_action', ''))
            if 'ENTRY_LONG' in action:
                direction = 'LONG'
                break
            elif 'ENTRY_SHORT' in action:
                direction = 'SHORT'
                break

    entry_price = float(latest.get('current_position_avg_price', 0))
    unrealized_pnl = float(latest.get('unrealized_pnl', 0))

    # Read position contract from CSV column, fallback to main_contract
    contract = ''
    if 'position_contract' in latest.index:
        contract = str(latest.get('position_contract', '') or '')
    if not contract:
        contract = main_contract

    # Calculate PnL percentage relative to notional value
    notional = entry_price * abs(size) * contract_multiplier
    unrealized_pnl_pct = (unrealized_pnl / notional * 100) if notional > 0 else 0.0

    # Hold days: count rows from last ENTRY to current row
    hold_days = 0
    for idx in range(len(trading_data) - 1, -1, -1):
        action = str(trading_data.iloc[idx].get('last_action', ''))
        if 'ENTRY' in action:
            hold_days = len(trading_data) - 1 - idx
            break

    return {
        'direction': direction,
        'contract': contract,
        'entry_price': entry_price,
        'unrealized_pnl': unrealized_pnl,
        'unrealized_pnl_pct': round(unrealized_pnl_pct, 2),
        'hold_days': hold_days,
    }


# =========================================================================
# Last Trade Action
# =========================================================================

def _build_last_trade(
    trading_data: Optional[pd.DataFrame],
    main_contract: str,
) -> Optional[Dict[str, Any]]:
    """Extract the last trade action (ENTRY/EXIT) from the most recent row.

    Returns None if no trade action occurred on the latest day.
    """
    if trading_data is None or trading_data.empty:
        return None

    latest = trading_data.iloc[-1]
    action = str(latest.get('last_action', ''))

    if 'ENTRY' not in action and 'EXIT' not in action:
        return None

    # Read action contract from CSV (new column), fallback to main_contract
    contract = ''
    if 'action_contract' in latest.index:
        contract = str(latest.get('action_contract', ''))
    if not contract:
        contract = main_contract

    return {
        'action': action,
        'price': float(latest.get('last_action_price', 0)),
        'contract': contract,
    }


# =========================================================================
# KPI Computation
# =========================================================================

def _compute_kpis(
    trading_data: Optional[pd.DataFrame],
    executions: Optional[pd.DataFrame],
) -> Dict[str, Any]:
    """Compute all KPIs from trading data and execution history.

    Minimum data requirements to avoid misleading annualized metrics:
      - Sharpe ratio:  ≥ 30 trading days
      - Annual return: ≥ 20 trading days
      - Max drawdown:  ≥ 10 trading days
    Below these thresholds the KPI stays None (displayed as "—").
    """
    MIN_DAYS_SHARPE = 30
    MIN_DAYS_ANNUAL_RETURN = 20
    MIN_DAYS_MAX_DRAWDOWN = 10

    kpis: Dict[str, Any] = {
        'sharpe_ratio': None,
        'annual_return': None,
        'max_drawdown': None,
        'win_rate': None,
        'profit_factor': None,
        'avg_hold_days': None,
        'trades_per_week': None,
    }

    if trading_data is not None and len(trading_data) >= 2:
        values = trading_data['total_account_value'].values
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

        # Annual return (annualized from first to last)
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

    # Trade-level metrics from executions
    if executions is not None and len(executions) > 0:
        # Filter to exit trades (they have realized_pnl)
        exits = executions[executions['direction'].str.contains('EXIT', na=False)]

        if len(exits) > 0:
            pnls = exits['realized_pnl'].astype(float)
            wins = pnls[pnls > 0]
            losses = pnls[pnls < 0]

            total_trades = len(exits)
            kpis['win_rate'] = round(len(wins) / total_trades, 3) if total_trades > 0 else 0.0

            if len(losses) > 0 and abs(losses.sum()) > 0:
                kpis['profit_factor'] = round(float(wins.sum()) / abs(float(losses.sum())), 2)
            elif len(wins) > 0:
                kpis['profit_factor'] = 99.0  # All winners, cap display

            # Trades per week
            if trading_data is not None and len(trading_data) >= 2:
                first_ts = trading_data['timestamp'].iloc[0]
                last_ts = trading_data['timestamp'].iloc[-1]
                weeks = max((last_ts - first_ts).days / 7.0, 1.0)
                kpis['trades_per_week'] = round(total_trades / weeks, 1)

            # Avg hold days — pair entries with exits chronologically
            entries = executions[executions['direction'].str.contains('ENTRY', na=False)]
            if len(entries) > 0 and len(exits) > 0:
                entry_times = entries['timestamp'].values
                exit_times = exits['timestamp'].values
                hold_days_list = []
                for j in range(min(len(entry_times), len(exit_times))):
                    days = (exit_times[j] - entry_times[j]) / pd.Timedelta(days=1)
                    if days >= 0:
                        hold_days_list.append(days)
                if hold_days_list:
                    kpis['avg_hold_days'] = round(sum(hold_days_list) / len(hold_days_list), 1)

    # Win rate from trading_data if no exit trades yet
    if kpis['win_rate'] is None and trading_data is not None and len(trading_data) > 0:
        latest = trading_data.iloc[-1]
        trade_count = int(latest.get('trade_count', 0))
        win_rate_raw = float(latest.get('win_rate', 0))
        if trade_count > 0:
            kpis['win_rate'] = round(win_rate_raw / 100.0, 3)

    return kpis


