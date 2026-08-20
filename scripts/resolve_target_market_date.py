from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from update_indices import call_ifind, parse_rows  # noqa: E402


def latest_ifind_session(as_of: date) -> date:
    """Resolve the last completed session from dates actually returned by iFinD."""
    end = as_of - timedelta(days=1)
    start = end - timedelta(days=14)
    query = (
        f"查询上证指数(000001.SH)在{start.isoformat()}至{end.isoformat()}逐交易日的收盘点位，"
        "必须逐日返回证券代码、日期和收盘点位；休市日不要返回。"
    )
    rows = parse_rows(call_ifind(query))
    sessions = {
        row["date"].date()
        for row in rows
        if row.get("index_code") == "000001.SH"
        and row.get("close") is not None
        and row["date"].date() <= end
    }
    if not sessions:
        raise RuntimeError(
            "iFinD returned no parseable Shanghai Composite sessions; "
            "the update is stopped to avoid treating a holiday as a trading day"
        )
    return max(sessions)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default=str(ROOT / "data" / "etf_flow.sqlite3"))
    parser.add_argument("--as-of", default=date.today().isoformat())
    args = parser.parse_args()
    if not Path(args.database).is_file():
        raise FileNotFoundError(f"Database not found: {args.database}")
    as_of = date.fromisoformat(args.as_of)
    print(latest_ifind_session(as_of).isoformat())


if __name__ == "__main__":
    main()
