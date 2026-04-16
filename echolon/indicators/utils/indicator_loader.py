"""
Indicator list loader for analysis configs.

Reads the analysis indicator JSON configs shipped with echolon
(indicators/config/{interday,intraday}_analysis_indicators.json)
and returns flat indicator lists used by the IndicatorProcessor
when computing the full indicator universe (selected=False).
"""
import json
import logging
from pathlib import Path
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent.parent / "config"


def load_analysis_indicators_config(frequency: str = "interday") -> Dict[str, Any]:
    """
    Load analysis indicator configuration for the specified frequency.

    Parameters
    ----------
    frequency : str
        'interday', 'day' -> interday config
        'intraday', 'minute' -> intraday config

    Returns
    -------
    Dict[str, Any]
        Full configuration including categorized indicators and metadata
    """
    if frequency in ("minute", "intraday"):
        config_file = CONFIG_DIR / "intraday_analysis_indicators.json"
    else:
        config_file = CONFIG_DIR / "interday_analysis_indicators.json"

    if not config_file.exists():
        logger.warning(f"Analysis indicators config not found: {config_file}")
        return {}

    with open(config_file, "r", encoding="utf-8") as f:
        config = json.load(f)

    logger.info(
        f"Loaded {config.get('indicator_count', 0)} analysis indicators for {frequency}"
    )
    return config


def get_analysis_indicator_list(frequency: str = "interday") -> List[str]:
    """
    Get flat list of indicators to analyze for the specified frequency.

    Parameters
    ----------
    frequency : str
        'interday' or 'intraday' (also accepts 'day' / 'minute')

    Returns
    -------
    List[str]
        List of indicator names to include in analysis
    """
    config = load_analysis_indicators_config(frequency)
    return config.get("all_indicators", [])
