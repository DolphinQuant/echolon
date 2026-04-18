"""
Statistical Utilities for Factor Analysis

Provides Information Coefficient (IC) calculation and significance testing.
Used by market_metrics for factor analysis and backtest_metrics for signal validation.
"""

import logging
import warnings
from typing import Tuple, Dict, Any, Optional

import pandas as pd
from scipy.stats import spearmanr

logger = logging.getLogger(__name__)


def calculate_ic_safe(
    factor_values: pd.Series,
    return_values: pd.Series,
    min_observations: int = 20
) -> Tuple[float, float]:
    """
    Calculate Spearman Information Coefficient with robust error handling.

    Parameters
    ----------
    factor_values : pd.Series
        Factor values to correlate
    return_values : pd.Series
        Return values to correlate
    min_observations : int
        Minimum observations required

    Returns
    -------
    Tuple[float, float]
        (IC value, p-value) or (0.0, 1.0) if calculation fails
    """
    # Combine and clean data
    clean_data = pd.DataFrame({
        'factor': factor_values,
        'returns': return_values
    }).dropna()

    # Check minimum observations
    if len(clean_data) < min_observations:
        return 0.0, 1.0

    # Check for constant values
    factor_unique = clean_data['factor'].nunique()
    return_unique = clean_data['returns'].nunique()

    if factor_unique <= 1:
        logger.debug(f"Factor has constant values ({factor_unique} unique)")
        return 0.0, 1.0

    if return_unique <= 1:
        logger.debug(f"Returns have constant values ({return_unique} unique)")
        return 0.0, 1.0

    # Calculate IC with warning suppression
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', message='An input array is constant')
        ic, p_value = spearmanr(clean_data['factor'], clean_data['returns'])

    # Handle NaN results
    if pd.isna(ic) or pd.isna(p_value):
        return 0.0, 1.0

    return ic, p_value


def filter_numeric_factors(
    factors_df: pd.DataFrame,
    exclude_cols: list = None
) -> pd.DataFrame:
    """
    Filter DataFrame to numeric factors, removing constants.

    Parameters
    ----------
    factors_df : pd.DataFrame
        DataFrame with factor columns
    exclude_cols : list
        Columns to exclude (default: regime columns)

    Returns
    -------
    pd.DataFrame
        Filtered numeric factors
    """
    if exclude_cols is None:
        exclude_cols = ['market_regime', 'market_regime_string']

    # Filter numeric columns
    numeric_cols = []
    for col in factors_df.columns:
        if col not in exclude_cols and pd.api.types.is_numeric_dtype(factors_df[col]):
            numeric_cols.append(col)

    numeric_factors = factors_df[numeric_cols].copy()

    # Remove constant indicators
    constant_cols = []
    for col in numeric_factors.columns:
        if numeric_factors[col].nunique() <= 1:
            constant_cols.append(col)
            logger.warning(f"Removing constant indicator: {col}")

    if constant_cols:
        numeric_factors = numeric_factors.drop(columns=constant_cols)
        logger.info(f"Removed {len(constant_cols)} constant indicators")

    return numeric_factors


def analyze_ic_by_regime(
    factor_data: pd.Series,
    return_data: pd.Series,
    regime_data: Optional[pd.Series] = None,
    min_observations: int = 20
) -> Dict[str, Dict[str, Any]]:
    """
    Calculate IC stratified by market regime.

    Parameters
    ----------
    factor_data : pd.Series
        Factor values
    return_data : pd.Series
        Return values
    regime_data : pd.Series, optional
        Market regime classifications
    min_observations : int
        Minimum observations per regime

    Returns
    -------
    Dict[str, Dict[str, Any]]
        IC results by regime (includes 'global')
    """
    results = {}

    # Global IC
    ic, p_value = calculate_ic_safe(factor_data, return_data, min_observations)
    results['global'] = {
        'information_coefficient': round(ic, 3),
        'p_value': round(p_value, 3),
        'observation_count': len(factor_data.dropna())
    }

    # Regime-specific IC
    if regime_data is not None and not regime_data.empty:
        combined = pd.DataFrame({
            'factor': factor_data,
            'returns': return_data,
            'regime': regime_data
        }).dropna()

        for regime in combined['regime'].unique():
            regime_slice = combined[combined['regime'] == regime]

            if len(regime_slice) >= min_observations:
                ic, p_value = calculate_ic_safe(
                    regime_slice['factor'],
                    regime_slice['returns'],
                    min_observations
                )
                results[regime] = {
                    'information_coefficient': round(ic, 3),
                    'p_value': round(p_value, 3),
                    'observation_count': len(regime_slice)
                }

    return results


def get_dynamic_min_observations(total_obs: int, min_pct: float = 0.01) -> int:
    """
    Calculate dynamic minimum observations threshold.

    Parameters
    ----------
    total_obs : int
        Total observations in dataset
    min_pct : float
        Minimum percentage of total

    Returns
    -------
    int
        Minimum observations (at least 20)
    """
    return max(20, int(total_obs * min_pct))


def rate_ic_quality(ic: float, p_value: float) -> str:
    """
    Rate IC quality for trading usefulness.

    Ratings:
    - NOT_SIGNIFICANT: p-value > 0.05
    - NOISE: |IC| < 0.02
    - WEAK: 0.02 <= |IC| < 0.05
    - MODERATE: 0.05 <= |IC| < 0.10
    - STRONG: |IC| >= 0.10

    Parameters
    ----------
    ic : float
        Information coefficient value
    p_value : float
        Statistical significance p-value

    Returns
    -------
    str
        Quality rating
    """
    if p_value > 0.05:
        return "NOT_SIGNIFICANT"

    abs_ic = abs(ic)

    if abs_ic < 0.02:
        return "NOISE"
    elif abs_ic < 0.05:
        return "WEAK"
    elif abs_ic < 0.10:
        return "MODERATE"
    else:
        return "STRONG"


def calculate_bonferroni_threshold(alpha: float = 0.05, num_tests: int = 1) -> float:
    """
    Calculate Bonferroni-corrected significance threshold.

    Parameters
    ----------
    alpha : float
        Desired family-wise error rate
    num_tests : int
        Number of independent tests

    Returns
    -------
    float
        Corrected significance threshold
    """
    if num_tests < 1:
        logger.warning(f"Invalid num_tests: {num_tests}, using 1")
        num_tests = 1
    return alpha / num_tests


def is_significant_after_correction(p_value: float, num_tests: int, alpha: float = 0.05) -> bool:
    """
    Check if p-value is significant after Bonferroni correction.

    Parameters
    ----------
    p_value : float
        Uncorrected p-value
    num_tests : int
        Number of independent tests
    alpha : float
        Desired family-wise error rate

    Returns
    -------
    bool
        True if significant after correction
    """
    corrected_threshold = calculate_bonferroni_threshold(alpha, num_tests)
    return p_value < corrected_threshold
