from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "processed" / "indices.parquet"
YAHOO_INDICES = {
    "GSPC": ("%5EGSPC", "美国", "标普500指数", "America/New_York"),
    "IXIC": ("%5EIXIC", "美国", "纳斯达克综合指数", "America/New_York"),
    "N225": ("%5EN225", "日本", "日经225指数", "Asia/Tokyo"),
    "KS11": ("%5EKS11", "韩国", "韩国综合指数", "Asia/Seoul"),
}


def fetch_yahoo_daily(code: str, start: pd.Timestamp, end: pd.Timestamp) -> list[dict]:
    symbol, country, name, market_timezone = YAHOO_INDICES[code]
    period1 = int(start.tz_localize("UTC").timestamp())
    period2 = int((end + pd.Timedelta(days=1)).tz_localize("UTC").timestamp())
    response = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}", params={"period1": period1, "period2": period2, "interval": "1d", "events": "history"}, headers={"User-Agent": "Mozilla/5.0"}, timeout=25)
    response.raise_for_status()
    result = response.json()["chart"]["result"][0]
    closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
    rows = []
    for timestamp, close in zip(result.get("timestamp", []), closes):
        if close is None or not pd.notna(close) or float(close) <= 0:
            continue
        trade_date = pd.Timestamp(datetime.fromtimestamp(timestamp, tz=timezone.utc)).tz_convert(market_timezone).normalize().tz_localize(None)
        if start <= trade_date <= end:
            rows.append({"date": trade_date, "country": country, "index_code": code, "index_name": name, "close": float(close), "change_pct": None, "source": "Yahoo Finance Chart API"})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    args = parser.parse_args()
    start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
    frame = pd.read_parquet(OUTPUT)
    frame["date"] = pd.to_datetime(frame["date"])
    target = frame["index_code"].isin(YAHOO_INDICES) & frame["date"].between(start, end)
    frame = frame.loc[~target].copy()
    rows = [row for code in YAHOO_INDICES for row in fetch_yahoo_daily(code, start, end)]
    if rows:
        frame = pd.concat([frame, pd.DataFrame(rows)], ignore_index=True)
    frame = frame.dropna(subset=["date", "index_code", "close"]).sort_values(["index_code", "date"]).drop_duplicates(["date", "index_code"], keep="last")
    frame["change_pct"] = frame.groupby("index_code")["close"].pct_change(fill_method=None) * 100
    frame["normalized"] = frame.groupby("index_code")["close"].transform(lambda series: series / series.iloc[0] * 100)
    frame = frame.sort_values(["date", "index_code"])
    frame.to_parquet(OUTPUT, index=False)
    latest = {code: str(frame.loc[frame["index_code"].eq(code), "date"].max().date()) for code in YAHOO_INDICES}
    print(json.dumps({"status": "pass", "added": len(rows), "latest_by_series": latest}, ensure_ascii=False))


if __name__ == "__main__":
    main()