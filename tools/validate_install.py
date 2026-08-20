from __future__ import annotations

import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "data" / "etf_catcher.sqlite3"
REQUIRED_TABLES = {"etf_master", "etf_daily", "panel_group_daily", "index_daily", "macro_payload", "etf_flow_estimates", "etf_direct_flow_observations"}
REQUIRED_WEB = {"meta.json", "indices.json", "groups.json", "etfs.json", "etf_daily.json", "rankings.json", "heatmap.json", "radar.json", "macro_monitor.json", "stable_fund_behavior.json"}


def main() -> None:
    checks = {}
    with sqlite3.connect(f"file:{DATABASE.as_posix()}?mode=ro", uri=True) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        checks["quick_check"] = connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        checks["tables"] = REQUIRED_TABLES.issubset(tables)
        checks["etf_rows"] = connection.execute("SELECT COUNT(*) FROM etf_daily").fetchone()[0] > 100_000
        checks["history_start"] = connection.execute("SELECT MIN(trade_date) FROM etf_daily").fetchone()[0]
        checks["history_not_before_2025"] = checks["history_start"] >= "2025-01-01"
        checks["market_latest"] = connection.execute("SELECT MAX(trade_date) FROM etf_daily WHERE close IS NOT NULL").fetchone()[0]
        checks["flow_latest"] = connection.execute("SELECT MAX(trade_date) FROM etf_daily WHERE net_flow IS NOT NULL").fetchone()[0]
    web = ROOT / "data" / "web"
    existing = {path.name for path in web.glob("*.json")}
    checks["web_files"] = REQUIRED_WEB.issubset(existing) and all((web / name).stat().st_size > 10 for name in REQUIRED_WEB)
    meta = json.loads((web / "meta.json").read_text(encoding="utf-8")) if (web / "meta.json").exists() else {}
    checks["dates_synced"] = meta.get("market_latest") == checks["market_latest"] and meta.get("flow_latest") == checks["flow_latest"]
    booleans = [value for key, value in checks.items() if key not in {"history_start", "market_latest", "flow_latest"}]
    status = "pass" if all(booleans) and checks["market_latest"] and checks["flow_latest"] else "fail"
    print(json.dumps({"status": status, "checks": checks}, ensure_ascii=False))
    raise SystemExit(0 if status == "pass" else 1)


if __name__ == "__main__":
    main()
