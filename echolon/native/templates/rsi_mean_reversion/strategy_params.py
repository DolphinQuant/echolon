"""RSI mean reversion parameters."""

from typing import Any, Dict


DEFAULT_PARAMS: Dict[str, Any] = {
    "entry_params": {"printlog": False, "rsi_period": 14, "oversold": 30},
    "exit_params": {"printlog": False, "rsi_period": 14, "overbought": 70},
    "risk_params": {"printlog": False},
    "sizer_params": {"printlog": False},
}


def optuna_search_space(trial):
    period = trial.suggest_int("rsi_period", 10, 20)
    return {
        "entry_params": {"printlog": False, "rsi_period": period,
                         "oversold": trial.suggest_int("oversold", 20, 35)},
        "exit_params": {"printlog": False, "rsi_period": period,
                        "overbought": trial.suggest_int("overbought", 65, 80)},
        "risk_params": {"printlog": False},
        "sizer_params": {"printlog": False},
    }


def apply_shared_params(params):
    return params


framework = None
