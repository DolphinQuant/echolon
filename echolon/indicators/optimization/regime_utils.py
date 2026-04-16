"""
Regime Classification Factor Analysis Utilities
================================================

RESEARCH UTILITY - NOT USED IN QR AGENT DATA DISTRIBUTION

This module provides utilities for analyzing which technical indicators
correlate with pre-defined market regimes. This is a RETROSPECTIVE analysis
tool that can help validate or improve regime classification logic.

Works with both:
- Interday (daily) regimes: 4 states (trending_up, trending_down, ranging, volatile)
- Intraday (minute) regimes: 5 states (+ choppy_low_volume, transitional)

CRITICAL DISTINCTION:
- market_regime.py/regime.py DEFINE regimes (the ground truth)
- This module ANALYZES which indicators correlate with those regime labels

USE CASES:
1. Validate that regime definition logic makes sense
   (e.g., verify ADX correlates with trending regimes)
2. Identify redundant indicators (proxies for regime itself)
3. Research alternative regime definition methods
4. Debug regime classification issues

NOT FOR:
- Strategy design (these factors classify regimes, NOT predict profitable entries)
- QR agent data distribution (creates confusion with predictive factors)
- Entry signal generation (correlates with WHAT regime is, not WHEN to enter)

See Also:
- interday_regime_optimizer.py: Optimize interday (daily) regime parameters
- intraday_regime_optimizer.py: Optimize intraday (minute) regime parameters
"""

import logging
from typing import Dict, List
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

logger = logging.getLogger(__name__)


def analyze_regime_classification_factors(
    df: pd.DataFrame,
    indicator_list: List[str]
) -> Dict[str, List[str]]:
    """
    Identifies factors that help CLASSIFY regimes using a RandomForest model.

    IMPORTANT: These are factors for REGIME CLASSIFICATION (identifying what regime we're in),
    NOT for ENTRY SIGNAL GENERATION (predicting profitable entries within a regime).

    Example: ADX helps classify "we're in trending_up" but doesn't tell you "enter now for profit."

    Method:
    1. Random Forest feature importance for globally important classification factors
    2. Z-score analysis for regime-specific characteristic factors

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame with market data, indicators, and 'market_regime_string' column
    indicator_list : List[str]
        List of indicator column names to analyze

    Returns
    -------
    Dict[str, List[str]]
        {
            "globally_important_for_classification": [top 5 factors],
            "NOTE": "These factors help CLASSIFY regimes, NOT predict profitable entries",
            "trending_up": [top 3 regime-specific factors],
            "trending_down": [...],
            ...
        }

    Notes
    -----
    This is a RESEARCH utility. Results should NOT be distributed to QR agent
    as they create confusion with predictive factors.
    """
    logger.info("Analyzing regime classification factors using feature importance...")

    # Filter factors to only include valid numeric columns
    valid_factors = []
    for f in indicator_list:
        if (f in df.columns and
            not df[f].isnull().all() and
            pd.api.types.is_numeric_dtype(df[f]) and
            f not in ['market_regime', 'market_regime_string']):
            valid_factors.append(f)

    logger.info(f"Using {len(valid_factors)} valid numeric factors for regime importance analysis")

    if len(valid_factors) == 0:
        logger.warning("No valid numeric factors found for regime analysis")
        return {"globally_important_for_classification": [], "NOTE": "Insufficient data"}

    # Ensure we have regime data
    if 'market_regime_string' not in df.columns:
        logger.warning("No market_regime_string column found")
        return {"globally_important_for_classification": [], "NOTE": "No regime data available"}

    combined_df = df.dropna(subset=['market_regime_string'] + valid_factors)

    if len(combined_df) < 50:
        logger.warning(f"Insufficient data for regime analysis: {len(combined_df)} samples")
        return {"globally_important_for_classification": [], "NOTE": "Insufficient samples"}

    X = combined_df[valid_factors]
    y = combined_df['market_regime_string']

    # Verify X contains only numeric data
    non_numeric_cols = []
    for col in X.columns:
        if not pd.api.types.is_numeric_dtype(X[col]):
            non_numeric_cols.append(col)

    if non_numeric_cols:
        logger.warning(f"Found non-numeric columns in features, removing: {non_numeric_cols}")
        X = X.drop(columns=non_numeric_cols)
        valid_factors = [f for f in valid_factors if f not in non_numeric_cols]

    if X.empty or len(valid_factors) == 0:
        logger.warning("No valid features remaining after filtering")
        return {"globally_important_for_classification": [], "NOTE": "No valid features"}

    # Check if we have enough regimes for classification
    unique_regimes = y.unique()
    if len(unique_regimes) < 2:
        logger.warning(f"Need at least 2 regimes for classification, found: {len(unique_regimes)}")
        return {"globally_important_for_classification": [], "NOTE": "Need at least 2 regimes"}

    # 1. Global Feature Importance (for distinguishing regimes)
    rf = RandomForestClassifier(n_estimators=100, random_state=42, n_jobs=-1)
    rf.fit(X, y)

    importances = pd.Series(rf.feature_importances_, index=valid_factors)
    globally_important_factors = importances.sort_values(ascending=False).head(5).index.tolist()

    # 2. Per-Regime Characteristic Factors (Z-score method)
    classification_factors = {
        "globally_important_for_classification": globally_important_factors,
        "NOTE": "These factors help CLASSIFY regimes, NOT predict profitable entries"
    }

    factor_means = X.mean()
    factor_stds = X.std()

    for regime in sorted(unique_regimes):
        regime_data = X[y == regime]
        if len(regime_data) < 5:  # Need minimum samples per regime
            continue

        regime_means = regime_data.mean()
        z_scores = (regime_means - factor_means) / factor_stds

        # Get top 3 factors with highest absolute Z-score for this regime
        top_factors = z_scores.abs().sort_values(ascending=False).head(3).index.tolist()
        classification_factors[regime] = top_factors

    logger.info(f"Identified regime classification factors for {len(classification_factors)-2} regimes (excluding global and NOTE).")
    return classification_factors


def validate_regime_definition(
    df: pd.DataFrame,
    indicator_list: List[str],
    expected_factors: List[str]
) -> Dict[str, any]:
    """
    Validate that regime definition logic aligns with statistical correlations.

    Use this to verify that the factors used in market_regime.py (e.g., ADX, SMA)
    actually show strong correlation with the regime labels.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame with market data, indicators, and 'market_regime_string'
    indicator_list : List[str]
        List of indicator column names
    expected_factors : List[str]
        Factors expected to be important (from market_regime.py logic)
        e.g., ['adx', 'sma_50', 'close']

    Returns
    -------
    Dict[str, any]
        {
            "classification_factors": {...},
            "validation_status": "PASS" or "WARNING",
            "expected_in_top_factors": [factors that appear in top 5],
            "missing_from_top_factors": [expected but not in top 5],
            "interpretation": "..."
        }
    """
    classification_result = analyze_regime_classification_factors(df, indicator_list)

    top_factors = classification_result.get("globally_important_for_classification", [])

    # Check which expected factors appear in top results
    expected_in_top = [f for f in expected_factors if f in top_factors]
    missing_from_top = [f for f in expected_factors if f not in top_factors]

    # Determine validation status
    if len(expected_in_top) == len(expected_factors):
        status = "PASS"
        interpretation = "All expected factors appear in top classification factors - regime definition is well-aligned with data."
    elif len(expected_in_top) > 0:
        status = "WARNING"
        interpretation = f"Some expected factors missing from top results: {missing_from_top}. Consider reviewing regime definition logic."
    else:
        status = "FAIL"
        interpretation = f"None of the expected factors appear in top classification factors. Regime definition may not align with actual market patterns."

    return {
        "classification_factors": classification_result,
        "validation_status": status,
        "expected_in_top_factors": expected_in_top,
        "missing_from_top_factors": missing_from_top,
        "interpretation": interpretation,
        "recommendation": (
            "If validation fails, either: "
            "(1) Revise market_regime.py logic to use factors that actually correlate with regimes, or "
            "(2) Re-examine whether regime labels are meaningful market states"
        )
    }
