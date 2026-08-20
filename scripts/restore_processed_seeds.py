from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default=str(ROOT / "data" / "etf_catcher.sqlite3"))
    args = parser.parse_args()
    output = ROOT / "data" / "processed"
    output.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{Path(args.database).as_posix()}?mode=ro", uri=True) as connection:
        indices = pd.read_sql_query("SELECT date,country,index_code,index_name,close,change_pct,normalized,source FROM index_daily", connection)
        macro = connection.execute("SELECT payload_json FROM macro_payload WHERE id=1").fetchone()
    indices["date"] = pd.to_datetime(indices["date"])
    indices.to_parquet(output / "indices.parquet", index=False)
    if macro:
        (ROOT / "data" / "web" / "macro_monitor.json").write_text(macro[0], encoding="utf-8")


if __name__ == "__main__":
    main()
