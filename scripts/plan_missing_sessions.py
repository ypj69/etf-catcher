from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from resolve_target_market_date import ifind_sessions  # noqa: E402


def parse_iso(value: object, label: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Invalid {label}: {value!r}") from exc


def published_watermark(database: Path, meta_path: Path) -> tuple[date, dict[str, str]]:
    if not database.is_file():
        raise FileNotFoundError(f"Database not found: {database}")
    if not meta_path.is_file():
        raise FileNotFoundError(f"Web metadata not found: {meta_path}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
        db_market = connection.execute(
            "SELECT MAX(trade_date) FROM etf_daily WHERE close IS NOT NULL"
        ).fetchone()[0]
        db_flow = connection.execute(
            "SELECT MAX(trade_date) FROM etf_daily WHERE net_flow IS NOT NULL"
        ).fetchone()[0]
    raw = {
        "meta_market": meta.get("market_latest"),
        "meta_flow": meta.get("flow_latest"),
        "database_market": db_market,
        "database_flow": db_flow,
    }
    if any(not value for value in raw.values()):
        raise RuntimeError(f"Cannot establish a complete publication watermark: {raw}")
    parsed = {key: parse_iso(value, key) for key, value in raw.items()}
    return min(parsed.values()), {key: value.isoformat() for key, value in parsed.items()}


def build_plan(database: Path, meta_path: Path, as_of: date) -> dict:
    watermark, evidence = published_watermark(database, meta_path)
    requested_end = as_of - timedelta(days=1)
    if watermark >= as_of:
        raise RuntimeError(
            f"Published watermark {watermark.isoformat()} cannot be on or after as-of {as_of.isoformat()}"
        )
    sessions = ifind_sessions(watermark + timedelta(days=1), requested_end)
    return {
        "status": "pass",
        "as_of": as_of.isoformat(),
        "published_through": watermark.isoformat(),
        "requested_end": requested_end.isoformat(),
        "dates": [item.isoformat() for item in sessions],
        "missing_count": len(sessions),
        "target_date": sessions[-1].isoformat() if sessions else watermark.isoformat(),
        "watermark_evidence": evidence,
        "calendar_source": "iFinD Shanghai Composite actual sessions",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default=str(ROOT / "data" / "etf_catcher.sqlite3"))
    parser.add_argument("--meta", default=str(ROOT / "data" / "web" / "meta.json"))
    parser.add_argument("--as-of", default=date.today().isoformat())
    args = parser.parse_args()
    plan = build_plan(Path(args.database), Path(args.meta), date.fromisoformat(args.as_of))
    print(json.dumps(plan, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
