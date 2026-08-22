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

from backfill_control import load_state  # noqa: E402
from resolve_target_market_date import actual_sessions  # noqa: E402
from validate_daily_web_coverage import coverage_report  # noqa: E402


MIN_COVERAGE = 0.95


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
    meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
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


def build_plan(
    database: Path,
    meta_path: Path,
    as_of: date,
    state_path: Path | None = None,
) -> dict:
    watermark, evidence = published_watermark(database, meta_path)
    requested_end = as_of - timedelta(days=1)
    if watermark >= as_of:
        raise RuntimeError(
            f"Published watermark {watermark.isoformat()} cannot be on or after as-of {as_of.isoformat()}"
        )
    sessions, calendar_source = actual_sessions(
        watermark + timedelta(days=1), requested_end
    )
    gap_dates = [item.isoformat() for item in sessions]
    state = load_state(state_path) if state_path else {"dates": {}}
    quarantined = {
        key
        for key, entry in state.get("dates", {}).items()
        if entry.get("quarantined")
    }

    pending: list[str] = []
    ready: list[str] = []
    reasons: dict[str, list[str]] = {}
    for trade_date in gap_dates:
        if trade_date in quarantined:
            continue
        report = coverage_report(database, trade_date, MIN_COVERAGE)
        if report["status"] == "pass":
            ready.append(trade_date)
        else:
            pending.append(trade_date)
            reasons[trade_date] = report["reasons"]

    target_date = gap_dates[-1] if gap_dates else watermark.isoformat()
    isolated = [value for value in gap_dates if value in quarantined]
    status = (
        "degraded"
        if isolated
        else "pending"
        if pending
        else "ready"
        if gap_dates
        else "complete"
    )
    return {
        "schema_version": 2,
        "status": status,
        "as_of": as_of.isoformat(),
        "published_through": watermark.isoformat(),
        "requested_end": requested_end.isoformat(),
        "window_start": gap_dates[0] if gap_dates else watermark.isoformat(),
        "gap_dates": gap_dates,
        "dates": pending,
        "ready_dates": ready,
        "quarantined_dates": isolated,
        "missing_count": len(pending),
        "target_date": target_date,
        "publication_required": bool(gap_dates),
        "watermark_evidence": evidence,
        "calendar_source": calendar_source,
        "coverage_threshold": MIN_COVERAGE,
        "scope": "sessions strictly after the last successful web publication",
        "reasons": reasons,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default=str(ROOT / "data" / "etf_catcher.sqlite3"))
    parser.add_argument("--meta", default=str(ROOT / "data" / "web" / "meta.json"))
    parser.add_argument(
        "--state", default=str(ROOT / "runtime" / "backfill_failures.json")
    )
    parser.add_argument("--as-of", default=date.today().isoformat())
    args = parser.parse_args()
    plan = build_plan(
        Path(args.database),
        Path(args.meta),
        date.fromisoformat(args.as_of),
        Path(args.state),
    )
    print(json.dumps(plan, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()