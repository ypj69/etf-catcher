from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "enrich_web_meta", ROOT / "scripts" / "enrich_web_meta.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_source_gaps_returns_only_quarantined_dates(tmp_path: Path) -> None:
    state = tmp_path / "backfill_failures.json"
    state.write_text(
        json.dumps(
            {
                "dates": {
                    "2026-08-20": {"failed_runs": 3, "quarantined": True},
                    "2026-08-21": {"failed_runs": 1, "quarantined": False},
                    "2026-08-19": {"failed_runs": 4, "quarantined": True},
                }
            }
        ),
        encoding="utf-8",
    )
    assert MODULE.source_gaps(state) == ["2026-08-19", "2026-08-20"]


def test_frontend_discloses_source_gap_count() -> None:
    frontend = (ROOT / "frontend" / "assets" / "app_v2.js").read_text(
        encoding="utf-8"
    )
    assert "m.source_gaps?.length" in frontend
    assert "源端缺口" in frontend