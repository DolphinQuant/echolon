"""Selected robust trial schema - contract for selected_robust_trial.json.

Producer: modules/quant_engine/backtest/optimization/trial_selector.py
Consumer: modules/backtest_metrics/utils/backtest_loader.py

Version: 1.0
Created: 2026-01-15

This schema defines the structure for the selected trial from Optuna optimization,
containing trial metadata, performance metrics, and optimized strategy parameters.
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Dict, Any, Optional


class TrialMetricsSchema(BaseModel):
    """Performance metrics for the selected trial."""
    model_config = ConfigDict(extra='allow')  # Allow additional metrics

    sharpe_ratio: float = Field(description="Sharpe ratio of the trial")
    annual_return: float = Field(description="Annualized return percentage")
    max_drawdown_pct: float = Field(
        description="Maximum drawdown percentage (negative value)"
    )


class SelectedTrialSchema(BaseModel):
    """
    Schema for selected_robust_trial.json.

    This file contains the trial selected from Optuna optimization based on
    robustness analysis (cluster stability, parameter stability).

    Attributes:
        trial_number: Optuna trial number
        selection_reason: Why this trial was selected
        cluster_id: ID of the parameter cluster this trial belongs to
        cluster_robustness_score: Robustness score of the cluster
        parameter_stability_score: Stability score of parameters
        metrics: Performance metrics (sharpe, return, drawdown)
        params: Strategy parameters (variable keys based on strategy)
    """
    model_config = ConfigDict(extra='allow')  # Forward compatibility

    # ========================================
    # TRIAL IDENTIFICATION
    # ========================================
    trial_number: int = Field(
        ge=0,
        description="Optuna trial number"
    )
    selection_reason: str = Field(
        description="Reason for selecting this trial"
    )

    # ========================================
    # CLUSTER ANALYSIS
    # ========================================
    cluster_id: int = Field(
        ge=0,
        description="Parameter cluster ID from robustness analysis"
    )
    cluster_robustness_score: float = Field(
        description="Robustness score of the cluster (-1 to 1)"
    )
    parameter_stability_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Parameter stability score (0 to 1)"
    )

    # ========================================
    # PERFORMANCE METRICS
    # ========================================
    metrics: TrialMetricsSchema = Field(
        description="Performance metrics for this trial"
    )

    # ========================================
    # STRATEGY PARAMETERS
    # ========================================
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optimized strategy parameters (variable keys)"
    )

    # ========================================
    # PARAMETER CLASSIFICATIONS
    # ========================================
    param_classifications: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Parameter FIXED/FLOAT/INT classifications from StrategyParameterFramework"
    )

    def get_param(self, key: str, default: Any = None) -> Any:
        """
        Get a parameter value with optional default.

        Parameters
        ----------
        key : str
            Parameter name
        default : Any, optional
            Default value if key not found

        Returns
        -------
        Any
            Parameter value or default
        """
        return self.params.get(key, default)

    def get_period_params(self) -> Dict[str, int]:
        """
        Extract all period parameters from params.

        Returns
        -------
        Dict[str, int]
            Mapping of indicator base name to period value
            e.g., {'atr': 15, 'willr': 14}
        """
        period_mapping = {}
        for key, value in self.params.items():
            if key.endswith('_period') and isinstance(value, (int, float)):
                # Extract indicator name: entry_atr_period -> atr
                parts = key.replace('_period', '').split('_')
                if len(parts) >= 2:
                    indicator_name = parts[-1]  # Last part is indicator name
                    period_mapping[indicator_name] = int(value)
        return period_mapping
