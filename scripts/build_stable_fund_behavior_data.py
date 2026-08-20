from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
DATABASE = ROOT / "data" / "etf_catcher.sqlite3"
CORE_ETFS = ("510300", "510310", "510330", "159919")
MARKET_INDEX = "000001.SH"
DISPLAY_START = pd.Timestamp("2026-01-01")
HISTORICAL_CUTOFF = DISPLAY_START - pd.Timedelta(days=1)
POSITION_WINDOW = 120
SHARE_CHANGE_WINDOW = 20
Z_WINDOW = 120
Z_MIN_PERIODS = 60
EVENT_Z_THRESHOLD = 2.0
EVENT_GAP_TRADING_DAYS = 5

STATE_LABELS = {
    "reverse_replenishment": "稳定资金正在逆向回补",
    "high_retreat": "稳定资金正在高位撤退",
    "low_watch": "低位关注",
    "high_watch": "高位关注",
    "neutral": "中性观察",
    "warming_up": "预热中",
}


def classify_state(position_pct: float, share_change_pct: float, z_score: float) -> str:
    if any(pd.isna(value) for value in (position_pct, share_change_pct, z_score)):
        return "warming_up"
    if position_pct <= 20 and share_change_pct > 0 and z_score >= EVENT_Z_THRESHOLD:
        return "reverse_replenishment"
    if position_pct >= 80 and share_change_pct < 0 and z_score <= -EVENT_Z_THRESHOLD:
        return "high_retreat"
    if position_pct <= 20:
        return "low_watch"
    if position_pct >= 80:
        return "high_watch"
    return "neutral"


def calculate_behavior(daily: pd.DataFrame, indices: pd.DataFrame) -> pd.DataFrame:
    required_daily = {"trade_date", "etf_code", "fund_share"}
    required_indices = {"date", "index_code", "close"}
    if missing := required_daily.difference(daily.columns):
        raise ValueError(f"ETF data missing columns: {sorted(missing)}")
    if missing := required_indices.difference(indices.columns):
        raise ValueError(f"index data missing columns: {sorted(missing)}")

    core = daily.loc[:, ["trade_date", "etf_code", "fund_share"]].copy()
    core["trade_date"] = pd.to_datetime(core["trade_date"], errors="coerce").dt.normalize()
    core["etf_code"] = core["etf_code"].astype(str).str.extract(r"(\d{6})", expand=False)
    core["fund_share"] = pd.to_numeric(core["fund_share"], errors="coerce")
    core = core.loc[core["etf_code"].isin(CORE_ETFS)].drop_duplicates(
        ["trade_date", "etf_code"], keep="last"
    )
    pivot = core.pivot(index="trade_date", columns="etf_code", values="fund_share").reindex(columns=CORE_ETFS)
    pivot = pivot.dropna(how="any").sort_index()
    if pivot.empty:
        raise ValueError("no complete four-ETF share observations")

    total = pivot.sum(axis=1).rename("total_share").to_frame()
    total["share_change_20d_pct"] = total["total_share"].pct_change(SHARE_CHANGE_WINDOW, fill_method=None) * 100
    historical = total["share_change_20d_pct"].shift(1)
    historical_mean = historical.rolling(Z_WINDOW, min_periods=Z_MIN_PERIODS).mean()
    historical_std = historical.rolling(Z_WINDOW, min_periods=Z_MIN_PERIODS).std()
    total["z120_hist"] = (
        total["share_change_20d_pct"] - historical_mean
    ) / historical_std.replace(0, np.nan)

    market = indices.loc[indices["index_code"].eq(MARKET_INDEX), ["date", "close"]].copy()
    market["date"] = pd.to_datetime(market["date"], errors="coerce").dt.normalize()
    market["close"] = pd.to_numeric(market["close"], errors="coerce")
    market = market.dropna().drop_duplicates("date", keep="last").set_index("date").sort_index()
    market_low = market["close"].rolling(POSITION_WINDOW, min_periods=POSITION_WINDOW).min()
    market_high = market["close"].rolling(POSITION_WINDOW, min_periods=POSITION_WINDOW).max()
    market["market_position_120_pct"] = (
        (market["close"] - market_low) / (market_high - market_low).replace(0, np.nan) * 100
    )

    frame = total.join(market, how="inner").sort_index()
    frame.index.name = "trade_date"
    frame["total_share_yi"] = frame["total_share"] / 1e8
    frame["state_code"] = [
        classify_state(position, change, z_score)
        for position, change, z_score in zip(
            frame["market_position_120_pct"], frame["share_change_20d_pct"], frame["z120_hist"]
        )
    ]
    frame["state_label"] = frame["state_code"].map(STATE_LABELS)
    return frame.reset_index()


def load_input_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read all warm-up history from the in-project public database."""
    with sqlite3.connect(f"file:{DATABASE.as_posix()}?mode=ro", uri=True) as connection:
        daily = pd.read_sql_query(
            "SELECT trade_date,etf_code,fund_share FROM etf_daily WHERE etf_code IN ('510300','510310','510330','159919')",
            connection,
        )
        indices = pd.read_sql_query(
            "SELECT date,index_code,close FROM index_daily WHERE index_code='000001.SH'",
            connection,
        )
    daily["trade_date"] = pd.to_datetime(daily["trade_date"], errors="coerce").dt.normalize()
    indices["date"] = pd.to_datetime(indices["date"], errors="coerce").dt.normalize()
    return daily, indices


def detect_state_events(frame: pd.DataFrame) -> list[dict]:
    """Merge nearby observations of the two three-factor semantic states."""
    event_codes = {"reverse_replenishment", "high_retreat"}
    x = frame.reset_index(drop=True).copy()
    candidates = x.loc[x["state_code"].isin(event_codes)]
    events: list[dict] = []
    current: dict | None = None

    for order, row in candidates.iterrows():
        new_group = (
            current is None
            or row["state_code"] != current["state_code"]
            or order - current["last_order"] > EVENT_GAP_TRADING_DAYS
        )
        if new_group:
            if current is not None:
                events.append(current)
            current = {
                "state_code": row["state_code"],
                "state_label": row["state_label"],
                "start_order": int(order),
                "end_order": int(order),
                "last_order": int(order),
                "candidate_days": 1,
            }
        else:
            current["end_order"] = int(order)
            current["last_order"] = int(order)
            current["candidate_days"] += 1
    if current is not None:
        events.append(current)

    latest_order = len(x) - 1
    output: list[dict] = []
    for event in events:
        start = x.iloc[event["start_order"]]
        end = x.iloc[event["end_order"]]
        output.append({
            "state_code": event["state_code"],
            "state_label": event["state_label"],
            "start_date": start["trade_date"].strftime("%Y-%m-%d"),
            "end_date": end["trade_date"].strftime("%Y-%m-%d"),
            "candidate_days": int(event["candidate_days"]),
            "is_active": bool(event["end_order"] == latest_order),
            "trigger": {
                "market_position_120_pct": serializable(start["market_position_120_pct"]),
                "share_change_20d_pct": serializable(start["share_change_20d_pct"]),
                "z120_hist": serializable(start["z120_hist"]),
            },
        })
    return output


def serializable(value):
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, (np.floating, float)):
        return float(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    return value


def build_payload(daily: pd.DataFrame, indices: pd.DataFrame) -> dict:
    frame = calculate_behavior(daily, indices)
    expected_latest = pd.to_datetime(daily["trade_date"], errors="coerce").max().normalize()
    market_latest = pd.to_datetime(
        indices.loc[indices["index_code"].eq(MARKET_INDEX), "date"], errors="coerce"
    ).max().normalize()
    latest = frame["trade_date"].max()
    if latest != expected_latest or latest != market_latest:
        raise ValueError(
            f"behavior data not synchronized: behavior={latest.date()}, ETF={expected_latest.date()}, index={market_latest.date()}"
        )

    frame = frame.loc[frame["trade_date"].ge(DISPLAY_START)].reset_index(drop=True)
    rows = []
    columns = [
        "trade_date", "close", "market_position_120_pct", "total_share_yi",
        "share_change_20d_pct", "z120_hist", "state_code", "state_label",
    ]
    for item in frame[columns].to_dict("records"):
        rows.append({key: serializable(value) for key, value in item.items()})
    if not rows:
        raise ValueError("no 2026+ behavior observations")
    latest_row = rows[-1]
    events = detect_state_events(frame)
    return {
        "status": "pass",
        "date": latest_row["trade_date"],
        "core_etfs": list(CORE_ETFS),
        "benchmark": {"index_code": MARKET_INDEX, "index_name": "上证指数", "window": POSITION_WINDOW},
        "method": {
            "share_change_window": SHARE_CHANGE_WINDOW,
            "z_window": Z_WINDOW,
            "z_min_periods": Z_MIN_PERIODS,
            "z_excludes_current_day": True,
            "low_position_pct": 20,
            "high_position_pct": 80,
            "event_z_threshold": EVENT_Z_THRESHOLD,
            "event_gap_trading_days": EVENT_GAP_TRADING_DAYS,
            "display_start": DISPLAY_START.strftime("%Y-%m-%d"),
            "historical_cutoff": HISTORICAL_CUTOFF.strftime("%Y-%m-%d"),
            "historical_data_used_for_warmup": True,
            "data_bridge": "local_seed_database",
        },
        "latest": latest_row,
        "events": events,
        "alert": {
            "active": latest_row["state_code"] in {"reverse_replenishment", "high_retreat"},
            "new_today": any(event["start_date"] == latest_row["trade_date"] for event in events),
            "state_code": latest_row["state_code"] if latest_row["state_code"] in {"reverse_replenishment", "high_retreat"} else None,
            "state_label": latest_row["state_label"] if latest_row["state_code"] in {"reverse_replenishment", "high_retreat"} else None,
        },
        "series": rows,
        "disclaimer": "状态观察，不是交易信号。",
    }


def main() -> None:
    output = ROOT / "data" / "web" / "stable_fund_behavior.json"
    daily, indices = load_input_frames()
    payload = build_payload(daily, indices)
    output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({
        "status": "pass",
        "date": payload["date"],
        "state": payload["latest"]["state_code"],
        "events": len(payload["events"]),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
