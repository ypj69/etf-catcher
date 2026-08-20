from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SKILL_CALL = Path(os.environ.get("IFIND_SKILL_DIR", Path.home() / ".codex" / "skills" / "ifind-finance-data")) / "call-node.js"
OUTPUT = ROOT / "data" / "processed" / "indices.parquet"
VALIDATION = ROOT / "runtime" / "index_update_validation.json"

CODE_MAP = {
    "SPX.GI": "GSPC",
    "IXIC.GI": "IXIC",
    "N225.GI": "N225",
    "KS11.GI": "KS11",
}
NAME_MAP = {
    "000001.SH": ("中国", "上证指数"),
    "000300.SH": ("中国", "沪深300"),
    "000688.SH": ("中国", "科创50"),
    "GSPC": ("美国", "标普500指数"),
    "IXIC": ("美国", "纳斯达克综合指数"),
    "N225": ("日本", "日经225指数"),
    "KS11": ("韩国", "韩国综合指数"),
}
QUERY_BATCHES = [
    "上证指数(000001.SH)、沪深300(000300.SH)、科创50(000688.SH)",
]

def parse_number(value: str) -> float | None:
    text = str(value).strip().replace("\\t", "").replace(",", "").rstrip("%元")
    try:
        return float(text) if text else None
    except ValueError:
        return None


def find_value(row: dict[str, str], prefixes: tuple[str, ...]) -> str:
    for key, value in row.items():
        if any(str(key).startswith(prefix) for prefix in prefixes):
            return value
    return ""


def parse_rows(answer: str) -> list[dict]:
    lines = [line.strip() for line in answer.splitlines() if line.strip().startswith("|")]
    if len(lines) < 3:
        return []
    header = [cell.strip() for cell in lines[0].strip("|").split("|")]
    rows: list[dict] = []
    for line in lines[2:]:
        values = [cell.strip() for cell in line.strip("|").split("|")]
        if len(values) != len(header):
            continue
        raw = dict(zip(header, values))
        raw_code = find_value(raw, ("证券代码", "指数代码"))
        code = CODE_MAP.get(raw_code, raw_code)
        digits = re.sub(r"\D", "", find_value(raw, ("日期", "交易日期")))
        if code not in NAME_MAP or len(digits) != 8:
            continue
        country, name = NAME_MAP[code]
        rows.append(
            {
                "date": pd.Timestamp(f"{digits[:4]}-{digits[4:6]}-{digits[6:]}") ,
                "country": country,
                "index_code": code,
                "index_name": name,
                "close": parse_number(find_value(raw, ("收盘价", "收盘点位", "收盘"))),
                "change_pct": parse_number(find_value(raw, ("涨跌幅",))),
                "source": "iFinD",
            }
        )
    return rows


def call_ifind(query: str) -> str:
    script = (
        f"const {{call}}=require({json.dumps(str(SKILL_CALL))});"
        f"call('index','index_data',{{query:{json.dumps(query, ensure_ascii=False)}}})"
        ".then(x=>console.log(JSON.stringify(x))).catch(e=>{console.error(e);process.exit(1)})"
    )
    response = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, encoding="utf-8", check=True
    )
    outer = json.loads(response.stdout)
    answers: list[str] = []
    for item in outer.get("data", {}).get("result", {}).get("content", []):
        item_outer = json.loads(item.get("text", "{}"))
        payload = item_outer.get("data", {})
        inner = json.loads(payload) if isinstance(payload, str) else payload
        answers.append(inner.get("answer", ""))
    return "\n".join(answers)


def load_base() -> pd.DataFrame:
    if not OUTPUT.exists():
        raise FileNotFoundError(f"No in-project index seed dataset found: {OUTPUT}")
    base = pd.read_parquet(OUTPUT)
    return base[["date", "country", "index_code", "index_name", "close", "change_pct", "source"]].copy()


def write_validation(frame: pd.DataFrame, added: pd.DataFrame, start: str, end: str) -> dict:
    requested_start = pd.Timestamp(start)
    requested_end = pd.Timestamp(end)
    window = frame.loc[frame["date"].between(requested_start, requested_end)]
    counts = {code: int((window["index_code"] == code).sum()) for code in NAME_MAP}
    latest = {
        code: str(group["date"].max().date())
        for code, group in frame.groupby("index_code")
        if code in NAME_MAP
    }
    status = "pass" if set(latest) == set(NAME_MAP) and not added.empty else "fail"
    report = {
        "status": status,
        "requested_start": start,
        "requested_end": end,
        "added_rows": int(len(added)),
        "window_rows_by_series": counts,
        "latest_by_series": latest,
        "note": "Only observations returned by iFinD are stored; no weekend, holiday or interpolated rows are created.",
    }
    VALIDATION.parent.mkdir(parents=True, exist_ok=True)
    VALIDATION.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    args = parser.parse_args()

    base = load_base()
    answers: list[str] = []
    for subjects in QUERY_BATCHES:
        query = (
            f"分别查询{subjects}在{args.start}至{args.end}逐交易日的收盘点位和涨跌幅，"
            "必须逐日返回证券代码、指数简称、日期、数值和单位；休市日不要返回。"
        )
        answers.append(call_ifind(query))

    added = pd.DataFrame(parse_rows("\n".join(answers)))
    if added.empty:
        write_validation(base, added, args.start, args.end)
        raise RuntimeError("iFinD returned no parseable index observations")

    frame = pd.concat([base, added], ignore_index=True)
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.dropna(subset=["date", "index_code", "close"])
    frame = frame.loc[frame["index_code"].isin(NAME_MAP)].copy()
    frame = frame.drop_duplicates(["date", "index_code"], keep="last")
    frame = frame.loc[frame["date"].dt.weekday.lt(5)].sort_values(["index_code", "date"])
    frame["normalized"] = frame.groupby("index_code")["close"].transform(lambda s: s / s.iloc[0] * 100)
    frame.to_parquet(OUTPUT, index=False)
    report = write_validation(frame, added, args.start, args.end)
    print(json.dumps({"rows": len(frame), "added": len(added), **report}, ensure_ascii=False))


if __name__ == "__main__":
    main()
