from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "data" / "etf_catcher.sqlite3"


def emit(value) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def rows(connection: sqlite3.Connection, sql: str, parameters=()) -> list[dict]:
    connection.row_factory = sqlite3.Row
    return [dict(row) for row in connection.execute(sql, parameters)]


def bounded_days(value: str) -> int:
    value = int(value)
    if not 1 <= value <= 500:
        raise ValueError("days must be between 1 and 500")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Read ETF Catcher data without arbitrary SQL")
    parser.add_argument("--database", default=str(DEFAULT_DATABASE))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    etf = sub.add_parser("etf")
    etf.add_argument("--code", required=True)
    etf.add_argument("--days", type=bounded_days, default=60)
    market = sub.add_parser("market")
    market.add_argument("--days", type=bounded_days, default=60)
    group = sub.add_parser("group")
    group.add_argument("--name", required=True)
    group.add_argument("--days", type=bounded_days, default=60)
    macro = sub.add_parser("macro")
    macro.add_argument("--full", action="store_true")
    args = parser.parse_args()

    database = Path(args.database).resolve()
    if not database.is_file():
        raise FileNotFoundError(f"database not found: {database}")
    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
        if args.command == "status":
            tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            dates = connection.execute(
                "SELECT MIN(trade_date),MAX(CASE WHEN close IS NOT NULL THEN trade_date END),"
                "MAX(CASE WHEN net_flow IS NOT NULL THEN trade_date END),COUNT(*) FROM etf_daily"
            ).fetchone()
            emit({"database": str(database), "history_start": dates[0], "market_latest": dates[1], "flow_latest": dates[2], "rows": dates[3], "tables": tables, "data_policy": "最新上一个完整交易日"})
        elif args.command == "etf":
            if len(args.code) != 6 or not args.code.isdigit():
                raise ValueError("code must contain six digits")
            meta = rows(connection, "SELECT * FROM etf_master WHERE etf_code=?", (args.code,))
            history = rows(connection, "SELECT trade_date,close,pct_change,fund_share,fund_scale,amount,net_flow,flow_source,data_status FROM etf_daily WHERE etf_code=? ORDER BY trade_date DESC LIMIT ?", (args.code, args.days))[::-1]
            emit({"meta": meta[0] if meta else None, "rows": history, "coverage": {"start": history[0]["trade_date"] if history else None, "end": history[-1]["trade_date"] if history else None}})
        elif args.command == "market":
            result = rows(connection, "SELECT trade_date,SUM(net_flow) AS net_flow,SUM(amount) AS amount,COUNT(*) AS etf_rows FROM etf_daily WHERE trade_date IN (SELECT DISTINCT trade_date FROM etf_daily ORDER BY trade_date DESC LIMIT ?) GROUP BY trade_date ORDER BY trade_date", (args.days,))
            emit({"rows": result, "coverage": {"start": result[0]["trade_date"] if result else None, "end": result[-1]["trade_date"] if result else None}})
        elif args.command == "group":
            names = [row[0] for row in connection.execute("SELECT DISTINCT group_name FROM panel_group_daily WHERE group_name LIKE ? ORDER BY group_name", (f"%{args.name}%",))]
            if not names:
                emit({"error": "group not found", "query": args.name, "suggestions": []})
                return
            selected = args.name if args.name in names else names[0]
            result = rows(connection, "SELECT * FROM panel_group_daily WHERE group_name=? ORDER BY trade_date DESC LIMIT ?", (selected, args.days))[::-1]
            emit({"group_name": selected, "matches": names[:20], "rows": result, "coverage": {"start": result[0]["trade_date"] if result else None, "end": result[-1]["trade_date"] if result else None}})
        else:
            payload = connection.execute("SELECT payload_json FROM macro_payload WHERE id=1").fetchone()
            if not payload:
                emit({"error": "macro payload not found"})
                return
            data = json.loads(payload[0])
            if args.full:
                emit(data)
                return
            tabs = {}
            for tab_id, tab in data.get("tabs", {}).items():
                tabs[tab_id] = {
                    "label": tab.get("label"),
                    "series": [
                        {key: series.get(key) for key in ("id", "label", "unit", "latest", "as_of", "source", "refresh_status", "note")}
                        for series in tab.get("series", [])
                    ],
                }
            emit({key: data.get(key) for key in ("generated_at", "target_date", "refresh_status", "errors")} | {"tabs": tabs})


if __name__ == "__main__":
    main()
