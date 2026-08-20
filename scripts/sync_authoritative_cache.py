from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default=str(ROOT / "data" / "etf_catcher.sqlite3"))
    args = parser.parse_args()
    groups = pd.read_parquet(ROOT / "data" / "processed" / "group_daily.parquet")
    indices = pd.read_parquet(ROOT / "data" / "processed" / "indices.parquet")
    macro_path = ROOT / "data" / "web" / "macro_monitor.json"
    macro = macro_path.read_text(encoding="utf-8")
    for column in ("trade_date",):
        groups[column] = pd.to_datetime(groups[column]).dt.strftime("%Y-%m-%d")
    indices["date"] = pd.to_datetime(indices["date"]).dt.strftime("%Y-%m-%d")
    with sqlite3.connect(args.database) as connection:
        groups.to_sql("panel_group_daily", connection, if_exists="replace", index=False)
        indices[["date", "country", "index_code", "index_name", "close", "change_pct", "normalized", "source"]].to_sql("index_daily", connection, if_exists="replace", index=False)
        connection.execute("CREATE TABLE IF NOT EXISTS macro_payload(id INTEGER PRIMARY KEY CHECK(id=1),payload_json TEXT NOT NULL,updated_at TEXT NOT NULL)")
        payload = json.loads(macro)
        connection.execute(
            "INSERT INTO macro_payload(id,payload_json,updated_at) VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET payload_json=excluded.payload_json,updated_at=excluded.updated_at",
            (json.dumps(payload, ensure_ascii=False, separators=(",", ":")), str(payload.get("generated_at") or "")),
        )
        connection.commit()


if __name__ == "__main__":
    main()
