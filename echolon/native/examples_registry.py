"""Registry of bundled example strategies."""

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXAMPLES_DIR = _REPO_ROOT / "examples"

AVAILABLE_EXAMPLES = ("01_minimal", "02_momentum_breakout", "03_rsi_mean_reversion")


def example_path(name: str) -> Path:
    if name not in AVAILABLE_EXAMPLES:
        raise KeyError(f"Unknown example: {name}. Available: {AVAILABLE_EXAMPLES}")
    path = EXAMPLES_DIR / name
    if not path.is_dir():
        raise FileNotFoundError(f"Example directory missing: {path}")
    return path
