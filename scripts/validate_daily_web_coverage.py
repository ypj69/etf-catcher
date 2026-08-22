from __future__ import annotations

import argparse
import json
import math
import sqlite3
from pathlib import Path


FIELDS = ("close", "amount", "fund_share", "fund_scale", "net_flow")


def coverage_report(database: Path, trade_date: str, minimum: float = 0.95) -> dict:
    with sqlite3.connect(database) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(etf_daily)").fetchall()
        }
        missing_columns = [field for field in FIELDS if field not in columns]
        if missing_columns:
            raise RuntimeError(f"etf_daily is missing columns: {missing_columns}")
        historical_peak = int(
            connection.execute(
                "SELECT COALESCE(MAX(rows),0) FROM ("
                "SELECT COUNT(*) AS rows FROM etf_daily WHERE trade_date<=? GROUP BY trade_date)",
                (trade_date,),
            ).fetchone()[0]
            or 0
        )
        row = connection.execute(
            "SELECT COUNT(*)," + ",".join(f"SUM({field} IS NOT NULL)" for field in FIELDS)
            + " FROM etf_daily WHERE trade_date=?",
            (trade_date,),
        ).fetchone()
    total = int(row[0] or 0)
    counts = {field: int(value or 0) for field, value in zip(FIELDS, row[1:])}
    expected = max(historical_peak, 1)
    reasons: list[str] = []
    if total < math.ceil(expected * minimum):
        reasons.append(f"daily_rows={total}/{expected}")
    if total:
        required_fields = math.ceil(total * minimum)
        for field, count in counts.items():
            if count < required_fields:
                reasons.append(f"{field}={count}/{total}")
    report = {
        "status": "pass" if not reasons else "incomplete",
        "trade_date": trade_date,
        "minimum_coverage": minimum,
        "expected_rows": expected,
        "daily_rows": total,
        "field_rows": counts,
        "reasons": reasons,
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--minimum-coverage", type=float, default=0.95)
    args = parser.parse_args()
    report = coverage_report(Path(args.database), args.date, args.minimum_coverage)
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    if report["status"] != "pass":
        raise SystemExit(2)


if __name__ == "__main__":
    main()

