from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
WEB = ROOT / "data" / "web"
OVERSEAS_INDEX_CODES = {"GSPC", "IXIC", "N225", "KS11"}
WEB_INDEX_START = pd.Timestamp("2026-01-01")


def records(frame: pd.DataFrame) -> list[dict]:
    copy = frame.copy()
    for column in copy.select_dtypes(include=["datetime", "datetimetz"]):
        copy[column] = copy[column].dt.strftime("%Y-%m-%d")
    copy = copy.astype(object).where(pd.notna(copy), None)
    return copy.to_dict("records")


def dump(name: str, value) -> None:
    (WEB / name).write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def prepare_indices_for_web(
    indices: pd.DataFrame,
    market_dates,
    latest_market: pd.Timestamp,
) -> pd.DataFrame:
    """Add explicitly flagged display-only carry rows on A-share market dates."""
    required = {"date", "index_code", "index_name", "country", "close", "change_pct", "normalized"}
    if missing := required.difference(indices.columns):
        raise ValueError(f"index data missing columns: {sorted(missing)}")

    latest_market = pd.Timestamp(latest_market).normalize()
    frame = indices.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame = frame.loc[frame["date"].notna() & frame["date"].le(latest_market)].copy()
    overseas = frame["index_code"].isin(OVERSEAS_INDEX_CODES)
    valid_overseas = (
        np.isfinite(pd.to_numeric(frame["close"], errors="coerce"))
        & pd.to_numeric(frame["close"], errors="coerce").gt(0)
        & np.isfinite(pd.to_numeric(frame["normalized"], errors="coerce"))
        & pd.to_numeric(frame["normalized"], errors="coerce").gt(0)
    )
    frame = frame.loc[~overseas | valid_overseas].copy()
    frame["source_date"] = frame["date"]
    frame["is_carried"] = False

    calendar = pd.DatetimeIndex(pd.to_datetime(pd.Series(market_dates), errors="coerce").dropna().dt.normalize().unique())
    calendar = calendar[(calendar >= WEB_INDEX_START) & (calendar <= latest_market)].sort_values()
    carry_rows: list[pd.Series] = []
    for code in OVERSEAS_INDEX_CODES:
        series = frame.loc[frame["index_code"].eq(code)].sort_values("date")
        if series.empty:
            continue
        existing_dates = set(series["date"])
        for target_date in calendar:
            if target_date in existing_dates:
                continue
            prior = series.loc[series["date"].lt(target_date)]
            if prior.empty:
                continue
            carried = prior.iloc[-1].copy()
            carried["date"] = target_date
            carried["source_date"] = prior.iloc[-1]["date"]
            carried["change_pct"] = 0.0
            carried["is_carried"] = True
            carry_rows.append(carried)

    if carry_rows:
        frame = pd.concat([frame, pd.DataFrame(carry_rows)], ignore_index=True)
    return frame.sort_values(["date", "index_code"]).drop_duplicates(["date", "index_code"], keep="first")


def main() -> None:
    WEB.mkdir(parents=True, exist_ok=True)
    master = pd.read_parquet(DATA / "etf_master.parquet")
    daily = pd.read_parquet(DATA / "etf_daily.parquet")
    groups = pd.read_parquet(DATA / "group_daily.parquet")
    indices = pd.read_parquet(DATA / "indices.parquet")
    latest_flow = daily.loc[daily["net_flow"].notna(), "trade_date"].max()
    latest_market = daily.loc[daily["close"].notna(), "trade_date"].max()
    summary = daily.loc[daily["trade_date"].eq(latest_flow)].copy()
    summary["net_flow_yi"] = summary["net_flow"] / 1e8
    summary["share_change_yi"] = summary["share_change_for_chart"] / 1e8
    top_in = summary.nlargest(10, "net_flow_yi")
    top_out = summary.nsmallest(10, "net_flow_yi")
    recent_dates = sorted(groups.loc[groups["net_flow_yi"].notna(), "trade_date"].unique())[-10:]
    heatmap = groups.loc[
        groups["trade_date"].isin(recent_dates) & groups["group_level"].isin(["broad", "industry"]),
        ["trade_date", "group_level", "group_name", "net_flow_yi"],
    ]
    web_indices = prepare_indices_for_web(
        indices,
        daily.loc[daily["close"].notna(), "trade_date"].unique(),
        latest_market,
    )
    dump("meta.json", {
        "generated_at": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
        "market_latest": latest_market.strftime("%Y-%m-%d"),
        "flow_latest": latest_flow.strftime("%Y-%m-%d"),
        "etf_count": int(master["etf_code"].nunique()),
        "group_count": int(groups[["group_level", "group_name"]].drop_duplicates().shape[0]),
        "net_flow_yi": float(summary["net_flow_yi"].sum()),
        "share_change_yi": float(summary["share_change_yi"].sum()),
        "total_scale_yi": float(summary["fund_scale"].sum() / 1e8),
    })
    index_columns = ["date", "source_date", "is_carried", "index_code", "index_name", "country", "close", "change_pct", "normalized"]
    dump("indices.json", records(web_indices.loc[web_indices["date"].ge(WEB_INDEX_START), index_columns]))
    dump("groups.json", records(groups[["trade_date", "group_level", "group_name", "active_etfs", "valid_flow_etfs", "net_flow_yi", "share_change_yi", "net_flow_ma20_yi", "share_change_ma20_yi", "total_scale", "total_amount"]]))
    dump("etfs.json", records(master[["etf_code", "exchange", "etf_name", "asset_group", "asset_class", "category_l1", "category_l2", "tracking_index_code", "tracking_index_name"]]))
    detail_columns = ["trade_date", "etf_code", "close", "pct_change", "fund_share", "fund_scale", "amount", "net_flow", "share_change_for_chart", "corporate_action_flag"]
    detail = daily[detail_columns].copy()
    for c in ["fund_share", "fund_scale", "amount", "net_flow", "share_change_for_chart"]:
        detail[c + "_yi"] = detail[c] / 1e8
    dump("etf_daily.json", records(detail.drop(columns=["fund_share", "fund_scale", "amount", "net_flow", "share_change_for_chart"])))
    ranking_columns = ["etf_code", "etf_name", "category_l1", "category_l2", "net_flow_yi", "share_change_yi", "pct_change", "fund_scale"]
    dump("rankings.json", {"date": latest_flow.strftime("%Y-%m-%d"), "inflow": records(top_in[ranking_columns]), "outflow": records(top_out[ranking_columns])})
    dump("heatmap.json", records(heatmap))
    carried_latest = web_indices.loc[web_indices["date"].eq(pd.Timestamp(latest_market)) & web_indices["is_carried"], "index_code"].tolist()
    print(json.dumps({"status": "pass", "web_files": len(list(WEB.glob("*.json"))), "market_latest": str(latest_market.date()), "flow_latest": str(latest_flow.date()), "carried_indices": carried_latest}, ensure_ascii=False))


if __name__ == "__main__":
    main()