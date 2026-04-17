"""Strategy templates shipped with Echolon."""

from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent

AVAILABLE_TEMPLATES = ("minimal", "momentum_breakout", "rsi_mean_reversion")


def template_path(name: str) -> Path:
    if name not in AVAILABLE_TEMPLATES:
        raise KeyError(f"Unknown template: {name}. Available: {AVAILABLE_TEMPLATES}")
    path = TEMPLATES_DIR / name
    if not path.is_dir():
        raise FileNotFoundError(f"Template directory missing: {path}")
    return path
