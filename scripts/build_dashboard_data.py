from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
KNOWN_EVENTS = {
    ("515880", "2026-02-02"): (3.0, "fund_announcement"),
    ("515050", "2026-05-12"): (3.0, "fund_announcement"),
    ("515880", "2026-07-03"): (2.0, "fund_announcement"),
}


def repair_text(value):
    if not isinstance(value, str) or not value:
        return value
    try:
        repaired = value.encode("latin1").decode("gb18030")
        return repaired if repaired else value
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


def read_source(database: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    master = pd.read_sql_query("SELECT * FROM etf_master WHERE enabled=1", connection)
    daily = pd.read_sql_query(
        """
        SELECT d.*, m.exchange, m.etf_name, m.asset_class, m.category_l1,
               m.category_l2, m.tracking_index_code, m.tracking_index_name
        FROM etf_daily d JOIN etf_master m USING(etf_code)
        WHERE m.enabled=1 AND d.trade_date >= '2026-01-01'
        ORDER BY d.etf_code, d.trade_date
        """,
        connection,
        parse_dates=["trade_date"],
    )
    connection.close()
    return master, daily


def clean(master: pd.DataFrame, daily: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    text_columns = [
        "etf_name", "asset_class", "category_l1", "category_l2",
        "tracking_index_name", "source_fund_type", "classification_rule",
    ]
    for frame in (master, daily):
        for column in text_columns:
            if column in frame:
                frame[column] = frame[column].map(repair_text)
    master["asset_group"] = master["asset_class"].replace(
        {"A股宽基": "股票型ETF", "A股行业": "股票型ETF", "A股策略": "股票型ETF", "A股主题": "股票型ETF",
         "跨境权益": "QDII", "货币": "货币ETF", "债券": "债券ETF", "商品": "商品ETF"}
    )
    daily = daily.merge(master[["etf_code", "asset_group"]], on="etf_code", how="left")
    numeric = ["fund_share", "fund_scale", "open", "high", "low", "close", "pct_change", "volume", "amount", "net_flow"]
    for column in numeric:
        daily[column] = pd.to_numeric(daily[column], errors="coerce")
        daily.loc[~np.isfinite(daily[column]), column] = np.nan
    scale_price_ratio = daily["fund_scale"] / daily["fund_share"] / daily["close"]
    daily["invalid_scale_unit"] = (
        daily[["fund_scale", "fund_share", "close"]].gt(0).all(axis=1)
        & ((scale_price_ratio < 0.01) | (scale_price_ratio > 100.0))
    )
    dates = pd.Index(sorted(daily["trade_date"].dropna().unique()))
    date_number = pd.Series(np.arange(len(dates)), index=dates)
    daily["market_date_number"] = daily["trade_date"].map(date_number)
    grouped = daily.groupby("etf_code", sort=False)
    daily["previous_date_number"] = grouped["market_date_number"].shift(1)
    daily["is_consecutive_market_day"] = daily["market_date_number"].sub(daily["previous_date_number"]).eq(1)
    for column in ["fund_share", "fund_scale", "close"]:
        daily[f"previous_{column}"] = grouped[column].shift(1).where(daily["is_consecutive_market_day"])
    daily["share_ratio"] = daily["fund_share"] / daily["previous_fund_share"]
    daily["scale_ratio"] = daily["fund_scale"] / daily["previous_fund_scale"]
    daily["next_close"] = grouped["close"].shift(-1)
    daily["integer_ratio"] = daily["share_ratio"].round().clip(2, 10)
    daily["ratio_error"] = (daily["share_ratio"] - daily["integer_ratio"]).abs() / daily["integer_ratio"]
    same_error = (daily["close"] / daily["previous_close"] * daily["integer_ratio"] - 1).abs()
    next_error = (daily["next_close"] / daily["close"] * daily["integer_ratio"] - 1).abs()
    price_error = pd.concat([same_error, next_error], axis=1).min(axis=1)
    event_mask = (
        daily["is_consecutive_market_day"] & daily["share_ratio"].ge(1.5)
        & daily["ratio_error"].le(0.08) & daily["scale_ratio"].sub(1).abs().le(0.35)
        & price_error.le(0.18)
    )
    daily["corporate_action_flag"] = event_mask
    daily["corporate_action_ratio"] = daily["integer_ratio"].where(event_mask)
    daily["corporate_action_source"] = np.where(event_mask, "rule_high_confidence", "")
    for (code, date), (ratio, source) in KNOWN_EVENTS.items():
        mask = daily["etf_code"].eq(code) & daily["trade_date"].eq(pd.Timestamp(date))
        daily.loc[mask, ["corporate_action_flag", "corporate_action_ratio", "corporate_action_source"]] = [True, ratio, source]
    daily["share_change_raw"] = (daily["fund_share"] - daily["previous_fund_share"]).where(daily["is_consecutive_market_day"])
    daily["share_change_for_chart"] = daily["share_change_raw"]
    mask = daily["corporate_action_flag"] & daily["previous_fund_share"].notna()
    daily.loc[mask, "share_change_for_chart"] = (
        daily.loc[mask, "fund_share"] - daily.loc[mask, "previous_fund_share"] * daily.loc[mask, "corporate_action_ratio"]
    )
    daily["flow_available"] = daily["net_flow"].notna()
    daily["share_change_available"] = daily["share_change_for_chart"].notna()
    events = daily.loc[daily["corporate_action_flag"], [
        "trade_date", "etf_code", "etf_name", "category_l1", "category_l2",
        "corporate_action_ratio", "corporate_action_source", "share_ratio", "scale_ratio",
        "fund_share", "previous_fund_share", "net_flow",
    ]].copy()
    keep = [
        "trade_date", "etf_code", "exchange", "etf_name", "asset_group", "asset_class",
        "category_l1", "category_l2", "tracking_index_code", "tracking_index_name",
        "fund_share", "fund_scale", "open", "high", "low", "close", "pct_change",
        "volume", "amount", "net_flow", "flow_source", "data_status",
        "share_change_raw", "share_change_for_chart", "corporate_action_flag",
        "corporate_action_ratio", "corporate_action_source", "flow_available", "share_change_available",
        "invalid_scale_unit",
    ]
    return master, daily[keep].sort_values(["trade_date", "etf_code"]), events


def aggregate(daily: pd.DataFrame) -> pd.DataFrame:
    definitions = [
        ("asset", ["asset_group"]),
        ("broad", ["category_l2"]),
        ("industry", ["category_l2"]),
    ]
    frames = []
    for level, columns in definitions:
        selected = daily
        if level == "broad":
            selected = selected.loc[selected["category_l1"].eq("宽基")]
        elif level == "industry":
            selected = selected.loc[selected["category_l1"].eq("行业")]
        selected = selected.copy()
        selected["group_name"] = selected[columns].astype(str).agg(" / ".join, axis=1)
        selected["net_flow_valid"] = selected["net_flow"].where(selected["flow_available"])
        selected["share_change_valid"] = selected["share_change_for_chart"].where(selected["share_change_available"])
        result = selected.groupby(["trade_date", "group_name"], as_index=False).agg(
            active_etfs=("etf_code", "nunique"),
            valid_flow_etfs=("net_flow_valid", "count"),
            net_flow=("net_flow_valid", lambda x: x.sum(min_count=1)),
            share_change=("share_change_valid", lambda x: x.sum(min_count=1)),
            total_scale=("fund_scale", lambda x: x.sum(min_count=1)),
            total_amount=("amount", lambda x: x.sum(min_count=1)),
            corporate_actions=("corporate_action_flag", "sum"),
        )
        result.insert(1, "group_level", level)
        frames.append(result)
    panel = pd.concat(frames, ignore_index=True)
    panel["net_flow_yi"] = panel["net_flow"] / 1e8
    panel["share_change_yi"] = panel["share_change"] / 1e8
    panel = panel.sort_values(["group_level", "group_name", "trade_date"])
    panel["net_flow_ma20_yi"] = panel.groupby(["group_level", "group_name"])["net_flow_yi"].transform(lambda s: s.rolling(20, 5).mean())
    panel["share_change_ma20_yi"] = panel.groupby(["group_level", "group_name"])["share_change_yi"].transform(lambda s: s.rolling(20, 5).mean())
    return panel


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default=str(ROOT / "data" / "etf_flow.sqlite3"))
    args = parser.parse_args()
    output = ROOT / "data" / "processed"
    output.mkdir(parents=True, exist_ok=True)
    master, raw = read_source(Path(args.database))
    master, daily, events = clean(master, raw)
    panel = aggregate(daily)
    master.to_parquet(output / "etf_master.parquet", index=False)
    daily.to_parquet(output / "etf_daily.parquet", index=False, compression="zstd")
    panel.to_parquet(output / "group_daily.parquet", index=False, compression="zstd")
    events.to_parquet(output / "corporate_actions.parquet", index=False)
    report = {
        "status": "pass",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market_latest": str(daily.loc[daily["close"].notna(), "trade_date"].max().date()),
        "flow_latest": str(daily.loc[daily["net_flow"].notna(), "trade_date"].max().date()),
        "rows": len(daily), "etfs": int(daily["etf_code"].nunique()),
        "groups": int(panel[["group_level", "group_name"]].drop_duplicates().shape[0]),
        "corporate_actions": len(events),
        "duplicate_keys": int(daily.duplicated(["trade_date", "etf_code"]).sum()),
        "invalid_scale_rows": int(daily["invalid_scale_unit"].sum()),
        "mojibake_remaining": int(master["etf_name"].astype(str).str.contains("[º½¿Õ¹ÉÌì]", regex=True).sum()),
    }
    if report["duplicate_keys"] or report["invalid_scale_rows"] or report["mojibake_remaining"]:
        report["status"] = "fail"
    (output / "quality_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
