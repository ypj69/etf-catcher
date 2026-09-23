from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import pandas as pd
from macro_freshness import evaluate_macro_freshness


ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_FLOW_SOURCES = {"estimated_share_change", "iFinD_get_fund_ownership"}
OVERSEAS_INDEX_CODES = {"GSPC", "IXIC", "N225", "KS11"}
MAX_OVERSEAS_CARRY_DAYS = 7


def embedded_freshness_matches(macro: dict, computed: dict) -> bool:
    return isinstance(macro.get("freshness"), dict) and macro["freshness"] == computed


def coverage_minimum(rows: int, ratio: float = 0.95) -> int:
    return max(1, int(rows * ratio))


def validate_overseas_index_dates(
    indices: pd.DataFrame,
    target: pd.Timestamp,
) -> tuple[bool, dict[str, str], dict[str, str]]:
    latest_by_series: dict[str, str] = {}
    carried_forward: dict[str, str] = {}
    valid = True
    for code in sorted(OVERSEAS_INDEX_CODES):
        series = indices.loc[indices["index_code"].eq(code), "date"].dropna()
        if series.empty:
            valid = False
            continue
        latest = pd.Timestamp(series.max()).normalize()
        latest_by_series[code] = str(latest.date())
        lag_days = int((target.normalize() - latest).days)
        if lag_days < 0 or lag_days > MAX_OVERSEAS_CARRY_DAYS:
            valid = False
        elif lag_days > 0:
            carried_forward[code] = str(latest.date())
    return valid, latest_by_series, carried_forward


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default=str(ROOT / "data" / "etf_flow.sqlite3"))
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    meta = json.loads((ROOT / "data" / "web" / "meta.json").read_text(encoding="utf-8"))
    groups = json.loads((ROOT / "data" / "web" / "groups.json").read_text(encoding="utf-8"))
    macro = json.loads((ROOT / "data" / "web" / "macro_monitor.json").read_text(encoding="utf-8"))
    connection = sqlite3.connect(args.database)
    row = connection.execute(
        """SELECT COUNT(*),
                  SUM(CASE WHEN market_source IS NOT NULL THEN 1 ELSE 0 END),
                  COUNT(close),COUNT(fund_share),COUNT(net_flow),
                  SUM(CASE WHEN net_flow IS NOT NULL AND flow_source='estimated_share_change' THEN 1 ELSE 0 END),
                  SUM(CASE WHEN net_flow IS NOT NULL AND flow_source='iFinD_get_fund_ownership' THEN 1 ELSE 0 END)
           FROM etf_daily WHERE trade_date=?""",
        (args.date,),
    ).fetchone()
    total, market_rows, close_n, share_n, flow_n, estimated_n, direct_n = map(int, row)
    changed = connection.execute(
        "SELECT COUNT(*) FROM etf_flow_estimates WHERE trade_date=? AND adjusted_share_change IS NOT NULL AND abs(adjusted_share_change)>0",
        (args.date,),
    ).fetchone()[0]
    invalid_scale = connection.execute(
        "SELECT COUNT(*) FROM etf_daily WHERE trade_date=? AND fund_scale>0 AND fund_share>0 AND close>0 "
        "AND (fund_scale/fund_share/close<0.01 OR fund_scale/fund_share/close>100)",
        (args.date,),
    ).fetchone()[0]
    table_exists = connection.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='etf_direct_flow_observations'"
    ).fetchone()[0]
    resolution_rows = (
        connection.execute(
            "SELECT COUNT(*) FROM etf_direct_flow_observations WHERE trade_date=? AND resolution IS NOT NULL",
            (args.date,),
        ).fetchone()[0]
        if table_exists
        else 0
    )
    group_db_latest = connection.execute("SELECT MAX(trade_date) FROM panel_group_daily").fetchone()[0]
    connection.close()
    indices = pd.read_parquet(ROOT / "data" / "processed" / "indices.parquet")
    indices["date"] = pd.to_datetime(indices["date"])
    overseas_valid, index_latest_by_series, overseas_carry_forward = validate_overseas_index_dates(
        indices, pd.Timestamp(args.date)
    )
    macro_freshness = evaluate_macro_freshness(macro, args.date)
    market_minimum = coverage_minimum(market_rows)
    flow_minimum = coverage_minimum(total)
    checks = {
        "rows": total > 0,
        "market_rows_present": market_rows > 0,
        "close_95pct": close_n >= market_minimum,
        "share_95pct": share_n >= market_minimum,
        "flow_95pct": flow_n >= flow_minimum,
        "all_flows_resolved": flow_n == estimated_n + direct_n,
        "resolution_audit_complete": resolution_rows == total,
        "share_source_fresh": changed >= max(1, int(total * 0.05)),
        "scale_unit_consistent": invalid_scale == 0,
        "meta_market_synced": meta.get("market_latest") == args.date,
        "meta_flow_synced": meta.get("flow_latest") == args.date,
        "group_database_synced": group_db_latest == args.date,
        "group_web_synced": bool(groups) and max(str(item.get("trade_date") or "") for item in groups) == args.date,
        "macro_key_series_fresh": macro_freshness["status"] == "pass",
        "macro_embedded_freshness_synced": embedded_freshness_matches(macro, macro_freshness),
        "macro_target_synced": macro.get("target_date") == args.date,
        "macro_tabs_complete": set(macro.get("tabs") or {}) == {"retail_flow", "credit_pmi", "overseas"},
        "processed_etf_cutoff": str(pd.read_parquet(ROOT / "data" / "processed" / "etf_daily.parquet")["trade_date"].max().date()) == args.date,
        "processed_index_not_ahead": indices["date"].max() <= pd.Timestamp(args.date),
        "overseas_indices_available": overseas_valid,
    }
    result = {
        "status": "pass" if all(checks.values()) else "fail",
        "date": args.date,
        "rows": total,
        "market_rows": market_rows,
        "flow_only_rows": total - market_rows,
        "close": close_n,
        "share": share_n,
        "flow": flow_n,
        "direct_flow": direct_n,
        "estimated_flow": estimated_n,
        "resolution_rows": resolution_rows,
        "group_database_latest": group_db_latest,
        "group_web_latest": max((str(item.get("trade_date") or "") for item in groups), default=None),
        "macro_freshness": macro_freshness,
        "macro_target_date": macro.get("target_date"),
        "share_changed": changed,
        "invalid_scale_rows": invalid_scale,
        "index_latest_by_series": index_latest_by_series,
        "overseas_carry_forward": overseas_carry_forward,
        "checks": checks,
    }
    (ROOT / "runtime" / "t1_sync_validation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
