from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASELINE_UNIVERSE = ROOT / "config" / "etf_universe.csv"
LOCAL_UNIVERSE = ROOT / "data" / "etf_universe.csv"


def active_universe_path() -> Path:
    """Return the user-maintained universe when present, otherwise the bundled baseline."""
    return LOCAL_UNIVERSE if LOCAL_UNIVERSE.exists() else BASELINE_UNIVERSE
