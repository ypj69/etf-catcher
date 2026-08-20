from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def records(frame: pd.DataFrame) -> list[dict]:
    copy = frame.copy()
    for column in copy.select_dtypes(include=["datetime", "datetimetz"]):
        copy[column] = copy[column].dt.strftime("%Y-%m-%d")
    copy = copy.astype(object).where(pd.notna(copy), None)
    return copy.to_dict("records")


def main() -> None:
    processed = ROOT / "data/processed"
    web = ROOT / "data/web"
    groups = pd.read_parquet(processed / "group_daily.parquet")
    daily = pd.read_parquet(processed / "etf_daily.parquet")
    latest = groups.loc[groups.net_flow_yi.notna(), "trade_date"].max()
    dates = sorted(groups.loc[groups.net_flow_yi.notna(), "trade_date"].unique())
    windows = {n: set(dates[-n:]) for n in (5, 10, 20)}
    latest_groups = groups.loc[groups.trade_date.eq(latest)].copy()
    summaries = []
    for (level, name), history in groups.groupby(["group_level", "group_name"], sort=False):
        row = history.loc[history.trade_date.eq(latest)]
        if row.empty:
            continue
        item = row.iloc[0]
        summaries.append({
            "group_level": level, "group_name": name,
            "net_flow_yi": item.net_flow_yi, "share_change_yi": item.share_change_yi,
            "amount_yi": item.total_amount / 1e8 if pd.notna(item.total_amount) else None,
            "active_etfs": item.active_etfs, "valid_flow_etfs": item.valid_flow_etfs,
            "flow_5d_yi": history.loc[history.trade_date.isin(windows[5]), "net_flow_yi"].sum(min_count=1),
            "flow_10d_yi": history.loc[history.trade_date.isin(windows[10]), "net_flow_yi"].sum(min_count=1),
            "flow_20d_yi": history.loc[history.trade_date.isin(windows[20]), "net_flow_yi"].sum(min_count=1),
            "net_flow_ma20_yi": item.net_flow_ma20_yi,
        })
    summary = pd.DataFrame(summaries)
    etf_latest = daily.loc[daily.trade_date.eq(latest)]
    valid = etf_latest.net_flow.notna()
    overview = {
        "date": latest.strftime("%Y-%m-%d"),
        "net_flow_yi": float(etf_latest.net_flow.sum(min_count=1) / 1e8),
        "share_change_yi": float(etf_latest.share_change_for_chart.sum(min_count=1) / 1e8),
        "turnover_yi": float(etf_latest.amount.sum(min_count=1) / 1e8),
        "inflow_etfs": int((etf_latest.loc[valid, "net_flow"] > 0).sum()),
        "outflow_etfs": int((etf_latest.loc[valid, "net_flow"] < 0).sum()),
        "flow_coverage_pct": float(valid.mean() * 100),
    }
    market = groups.loc[groups.group_level.eq("asset")].groupby("trade_date", as_index=False).agg(
        net_flow_yi=("net_flow_yi", lambda s: s.sum(min_count=1)),
        share_change_yi=("share_change_yi", lambda s: s.sum(min_count=1)),
    ).tail(20)
    signals = []
    for (level, name), history in groups.groupby(["group_level", "group_name"]):
        if level == "asset":
            continue
        history = history.sort_values("trade_date").tail(20)
        vals = history.net_flow_yi.dropna()
        if len(vals) < 6:
            continue
        latest_flow = float(vals.iloc[-1]); prior5 = float(vals.iloc[-6:-1].mean())
        streak = 0
        for value in vals.iloc[::-1]:
            if value == 0 or (streak and np.sign(value) != np.sign(streak)):
                break
            streak += int(np.sign(value))
        signals.append({"group_level": level, "group_name": name, "latest_yi": latest_flow,
                        "acceleration_yi": latest_flow - prior5, "streak": streak,
                        "reversal": bool(np.sign(latest_flow) != np.sign(vals.iloc[-2]))})
    signals = pd.DataFrame(signals).sort_values("acceleration_yi", ascending=False)
    heat = groups.loc[groups.group_level.isin(["asset", "broad", "industry"])].copy()
    heat["abs_flow"] = heat.net_flow_yi.abs()
    heat["strength"] = heat.groupby(["group_level", "group_name"])["abs_flow"].rank(pct=True) * np.sign(heat.net_flow_yi)
    heat = heat.loc[heat.trade_date.isin(windows[10]), ["trade_date", "group_level", "group_name", "net_flow_yi", "share_change_yi", "strength"]]
    payload = {"overview": overview, "category_summary": records(summary), "market_trend": records(market),
               "signals": records(signals), "heatmap": records(heat)}
    (web / "radar.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({"status": "pass", "date": overview["date"], "categories": len(summary), "signals": len(signals)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
