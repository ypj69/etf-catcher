from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from etf_flow.scale_validation import count_invalid_scales


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default=str(ROOT / "data" / "etf_flow.sqlite3"))
    parser.add_argument("--date")
    parser.add_argument("--report", default=str(ROOT / "runtime" / "scale_unit_validation.json"))
    args = parser.parse_args()
    connection = sqlite3.connect(args.database)
    invalid = count_invalid_scales(connection, args.date)
    connection.close()
    result = {
        "status": "pass" if invalid == 0 else "fail",
        "date": args.date,
        "invalid_scale_rows": invalid,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    if invalid:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
