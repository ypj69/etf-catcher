from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "data" / "web"

def main():
    meta_path = WEB / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    daily = pd.read_parquet(ROOT / "data" / "processed" / "etf_daily.parquet", columns=["trade_date", "close"])
    days = pd.DatetimeIndex(sorted(pd.to_datetime(daily.loc[daily.close.notna(), "trade_date"]).dt.normalize().unique()))
    start, end = pd.Timestamp("2026-01-01"), pd.Timestamp(meta["market_latest"])
    weekdays = pd.date_range(start, end, freq="B")
    market = set(days.strftime("%Y-%m-%d"))
    meta["non_trading_weekdays"] = [x for x in weekdays.strftime("%Y-%m-%d") if x not in market]
    etfs = json.loads((WEB / "etfs.json").read_text(encoding="utf-8"))
    covered = sum(bool(x.get("tracking_index_name") or x.get("tracking_index_code")) for x in etfs)
    meta["tracking_index_covered"] = covered
    meta["tracking_index_coverage_pct"] = round(covered / len(etfs) * 100, 1) if etfs else 0
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({"status":"pass","non_trading_weekdays":len(meta["non_trading_weekdays"]),"tracking_index_covered":covered}, ensure_ascii=False))

if __name__ == "__main__": main()
