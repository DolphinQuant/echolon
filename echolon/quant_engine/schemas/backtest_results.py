"""Backtest results schema - contract between quant_engine and backtest_metrics.

Producer: modules/quant_engine/backtest/engine/backtrader_engine.py
Consumer: modules/backtest_metrics/utils/backtest_loader.py

Version: 4.0
Updated: 2026-01-15

Breaking changes from v3.0:
- Renamed sharpe_ratio → sharpe_ratio_annual
- Added trade_analyzer_details nested structure
- Standardized field naming conventions
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Dict, List, Optional, Any


# ============================================================================
# Trade Analyzer Nested Schemas
# ============================================================================

class TradeAnalyzerStreakSchema(BaseModel):
    """Streak statistics for won/lost trades."""
    current: int = Field(ge=0)
    longest: int = Field(ge=0)


class TradeAnalyzerPnLSchema(BaseModel):
    """PnL statistics."""
    total: float
    average: float
    max: Optional[float] = None


class TradeAnalyzerWonLostSchema(BaseModel):
    """Won/Lost trade statistics."""
    total: int = Field(ge=0)
    pnl: TradeAnalyzerPnLSchema


class TradeAnalyzerLengthStatsSchema(BaseModel):
    """Trade length statistics."""
    total: int = Field(ge=0)
    average: float
    max: int = Field(ge=0)
    min: int = Field(ge=0)
    won: Optional[Dict[str, Any]] = None
    lost: Optional[Dict[str, Any]] = None


class TradeAnalyzerDirectionSchema(BaseModel):
    """Long/Short direction breakdown."""
    model_config = ConfigDict(extra='allow')

    total: int = Field(ge=0)
    pnl: Dict[str, Any]  # Complex nested structure
    won: int = Field(ge=0)
    lost: int = Field(ge=0)


class TotalSchema(BaseModel):
    """Total trades breakdown."""
    total: int
    open: int = 0  # Default 0 for zero-trade backtests
    closed: int


class StreakSchema(BaseModel):
    """Streak statistics."""
    won: TradeAnalyzerStreakSchema
    lost: TradeAnalyzerStreakSchema


class GrossNetPnLSchema(BaseModel):
    """Gross/Net PnL breakdown."""
    total: float
    average: float


class PnLSchema(BaseModel):
    """Overall PnL structure."""
    gross: GrossNetPnLSchema
    net: GrossNetPnLSchema


class TradeAnalyzerDetailsSchema(BaseModel):
    """Backtrader TradeAnalyzer output schema."""
    model_config = ConfigDict(extra='allow')  # Allow extra fields

    total: TotalSchema
    streak: StreakSchema
    pnl: PnLSchema
    won: TradeAnalyzerWonLostSchema
    lost: TradeAnalyzerWonLostSchema

    # Optional long/short breakdown
    long: Optional[TradeAnalyzerDirectionSchema] = None
    short: Optional[TradeAnalyzerDirectionSchema] = None

    # Optional trade length statistics
    len: Optional[TradeAnalyzerLengthStatsSchema] = None


class TimeDrawdownSchema(BaseModel):
    """Time-based drawdown analysis."""
    model_config = ConfigDict(extra='allow')

    max_drawdown_duration: int = Field(ge=0)
    drawdown_periods: Dict[str, Any] = Field(default_factory=dict)
    money_down_periods: Dict[str, Any] = Field(default_factory=dict)


class PeriodStatsSchema(BaseModel):
    """Period statistics (annual returns analysis)."""
    average: float
    stddev: float = Field(ge=0.0)
    positive: int = Field(ge=0)
    negative: int = Field(ge=0)
    nochange: int = Field(ge=0)
    best: float
    worst: float


# ============================================================================
# Performance Metrics Schema
# ============================================================================

class PerformanceMetricsSchema(BaseModel):
    """Top-level performance metrics from backtrader analyzers."""
    model_config = ConfigDict(extra='allow')

    # ========================================
    # REQUIRED FIELDS (Core KPIs)
    # ========================================
    sharpe_ratio_annual: float = Field(
        description="Annualized Sharpe ratio from backtrader's SharpeRatio analyzer"
    )
    total_return_pct: float = Field(
        description="Total return percentage over backtest period"
    )
    max_drawdown_pct: float = Field(
        description="Maximum drawdown percentage (positive value in current format)"
    )
    total_trades: int = Field(
        description="Total number of closed trades",
        ge=0
    )
    winning_trades: int = Field(ge=0)
    losing_trades: int = Field(ge=0)
    win_rate_pct: float = Field(ge=0.0, le=100.0)

    initial_value: float = Field(gt=0)
    final_value: float = Field(gt=0)

    # Additional basic fields
    initial_capital: float = Field(gt=0)
    final_portfolio_value: float = Field(gt=0)
    trades_open: int = Field(ge=0)
    trades_closed: int = Field(ge=0)

    win_rate_analyzer: float = Field(ge=0.0, le=100.0)
    avg_win_pnl: float
    avg_loss_pnl: float
    profit_factor_analyzer: float = Field(ge=0.0)

    # ========================================
    # OPTIONAL FIELDS (Extended metrics)
    # ========================================
    sharpe_ratio_monthly: Optional[float] = None
    sharpe_ratio_weekly: Optional[float] = None
    calmar_ratio: Optional[float] = None
    sqn: Optional[float] = Field(None, description="System Quality Number")
    vwr: Optional[float] = Field(None, description="Variability-Weighted Return")

    average_annual_return_pct: Optional[float] = None
    max_drawdown_len: Optional[int] = Field(None, ge=0)

    # ========================================
    # COMPLEX NESTED STRUCTURES
    # ========================================
    trade_analyzer_details: Optional[TradeAnalyzerDetailsSchema] = None
    time_drawdown: Optional[TimeDrawdownSchema] = None
    period_stats: Optional[PeriodStatsSchema] = None

    # Time-based returns (can be large, allow as optional dict)
    daily_returns: Optional[Dict[str, float]] = Field(
        default=None,
        description="Daily returns dict {date_str: return_pct}"
    )
    monthly_returns: Optional[Dict[str, float]] = None
    annual_returns: Optional[Dict[str, float]] = None
    weekly_returns: Optional[Dict[str, float]] = None


# ============================================================================
# Top-Level Backtest Results Schema
# ============================================================================

# ============================================================================
# Walk-Forward Analysis (WFA) Schemas
# ============================================================================

class WFAWindowDetailSchema(BaseModel):
    """Per-window WFA detail."""
    model_config = ConfigDict(extra='allow')

    window_id: int
    is_start: str
    is_end: str
    oos_start: str
    oos_end: str
    is_years: float
    oos_years: float
    is_sharpe: Optional[float] = None
    oos_sharpe: Optional[float] = None
    walk_forward_efficiency: Optional[float] = None
    oos_metrics: Optional[Dict[str, Any]] = None
    selected_trial_number: Optional[int] = None


class WFASummarySchema(BaseModel):
    """WFA aggregate summary metrics."""
    model_config = ConfigDict(extra='allow')

    total_windows: int
    completed_windows: int
    windows_zero_trades: int = 0
    wfe_mean: Optional[float] = None
    wfe_min: Optional[float] = None
    wfe_max: Optional[float] = None
    oos_sharpe_mean: Optional[float] = None
    oos_sharpe_std: Optional[float] = None
    oos_sharpe_min: Optional[float] = None
    oos_sharpe_consistency: Optional[float] = None
    parameter_stability_cv: Optional[Dict[str, float]] = None
    degradation_ratios: Optional[list] = None
    windows_positive_oos: int = 0


# ============================================================================
# Deployment Readiness Score (DRS) Schemas
# ============================================================================

class DRSGateResultSchema(BaseModel):
    """Result of a single DRS hard gate check."""
    gate_id: str = Field(description="Gate identifier (G1-G6)")
    passed: bool
    value: float
    threshold: float
    description: str


class DRSComponentSchema(BaseModel):
    """Score for a single DRS component."""
    name: str = Field(description="Component name: oos_return, return_level, oos_edge, temporal_stability, oos_risk, param_confidence, gate_bonus")
    score: float = Field(ge=0.0)
    max_score: float = Field(gt=0.0)
    details: Dict[str, Any] = Field(default_factory=dict)


class DRSSchema(BaseModel):
    """Deployment Readiness Score — composite 0-100 score measuring deployment readiness.

    Architecture: Constrained Return Maximization
    - Return components (40pts): oos_return (25pts) + return_level (15pts)
    - Robustness components (35pts): oos_edge (20pts) + temporal_stability (15pts)
    - Risk constraint (10pts): oos_risk
    - Quality (8pts): param_confidence
    - Bonus (7pts): gate_bonus
    - 6 hard gates (G1-G6) must all pass or DRS=0
    """
    model_config = ConfigDict(extra='allow')

    drs_score: float = Field(ge=0.0, le=100.0, description="Composite DRS (0-100)")
    gates_passed: bool = Field(description="True if all 6 hard gates passed")
    weighted_oos_annual_return_pct: float = Field(
        description="Recency-weighted mean OOS annual return percentage"
    )
    recency_weighted_oos_sharpe: Optional[float] = Field(
        default=None,
        description="Deprecated: use weighted_oos_annual_return_pct instead"
    )
    gate_results: List[DRSGateResultSchema] = Field(
        description="Per-gate pass/fail details (G1-G6)"
    )
    components: Optional[List[DRSComponentSchema]] = Field(
        default=None,
        description="Per-component scores (only present when gates pass)"
    )
    component_breakdown: Optional[Dict[str, float]] = Field(
        default=None,
        description="Component name → score mapping (only present when gates pass)"
    )


class BacktestResultsSchemaV4(BaseModel):
    """
    Backtest results schema - contract between quant_engine and backtest_metrics.

    Producer: modules/quant_engine/backtest/engine/backtrader_engine.py
    Consumer: modules/backtest_metrics/utils/backtest_loader.py

    Version: 4.0
    Updated: 2026-01-15

    Breaking changes from v3.0:
    - Renamed sharpe_ratio → sharpe_ratio_annual
    - Added trade_analyzer_details nested structure
    - Standardized field naming conventions
    """
    model_config = ConfigDict(extra='allow')  # Forward compatibility

    # ========================================
    # METADATA
    # ========================================
    schema_version: str = Field(
        default='4.0',
        description="Schema version for migration support"
    )
    run_timestamp: str = Field(
        description="ISO format timestamp of backtest run"
    )
    run_context: str = Field(
        default="best_trial",
        description="Context: best_trial, optimization, manual"
    )

    # ========================================
    # MARKET METADATA
    # ========================================
    market: str = Field(description="Market code: SHFE, CRYPTO, CME")
    instrument: Optional[str] = Field(None, description="Instrument name (e.g., 'aluminum', 'bitcoin')")
    instrument_code: Optional[str] = Field(None, description="Instrument code (e.g., 'al', 'btc')")

    # ========================================
    # PERFORMANCE METRICS (REQUIRED)
    # ========================================
    performance_metrics: PerformanceMetricsSchema

    # ========================================
    # STRATEGY PARAMETERS
    # ========================================
    strategy_parameters: Dict[str, Any] = Field(default_factory=dict)

    # ========================================
    # WFA FIELDS (Optional - present when WFA_ENABLED)
    # ========================================
    wfa_summary: Optional[WFASummarySchema] = Field(
        default=None,
        description="Walk-Forward Analysis aggregate metrics"
    )
    wfa_windows: Optional[List[WFAWindowDetailSchema]] = Field(
        default=None,
        description="Per-window WFA details"
    )

    # ========================================
    # DRS (Optional - computed after WFA)
    # ========================================
    drs: Optional[DRSSchema] = Field(
        default=None,
        description="Deployment Readiness Score (0-100) from OOS metrics"
    )
