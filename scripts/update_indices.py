from __future__ import annotations

import argparse
import base64
import json
import locale
import math
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SKILL_CALL = Path(os.environ.get("IFIND_SKILL_DIR", Path.home() / ".codex" / "skills" / "ifind-finance-data")) / "call-node.js"
OUTPUT = ROOT / "data" / "processed" / "indices.parquet"
VALIDATION = ROOT / "runtime" / "index_update_validation.json"
CALL_STATUS = ROOT / "runtime" / "index_ifind_call_status.json"
RETRY_DELAYS = (2.0, 5.0)
TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
TENCENT_SYMBOLS = {
    "000001.SH": "sh000001",
    "000300.SH": "sh000300",
    "000688.SH": "sh000688",
}

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


def decode_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    for encoding in dict.fromkeys(("utf-8-sig", locale.getpreferredencoding(False), "mbcs")):
        try:
            return value.decode(encoding).strip()
        except (LookupError, UnicodeDecodeError):
            continue
    return value.decode("utf-8", errors="replace").strip()


def write_call_status(status: str, attempts: list[dict]) -> None:
    CALL_STATUS.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": status,
        "updated_at": datetime.now().astimezone().isoformat(),
        "attempt_count": len(attempts),
        "attempts": attempts,
    }
    CALL_STATUS.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def call_ifind(query: str, retry_delays: tuple[float, ...] = RETRY_DELAYS) -> str:
    encoded_query = base64.b64encode(query.encode("utf-8")).decode("ascii")
    script = (
        f"const {{call}}=require({json.dumps(str(SKILL_CALL))});"
        f"const query=Buffer.from('{encoded_query}','base64').toString('utf8');"
        "call('index','index_data',{query})"
        ".then(x=>console.log(JSON.stringify(x))).catch(e=>{console.error(e);process.exit(1)})"
    )
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    attempts: list[dict] = []
    response: subprocess.CompletedProcess[bytes] | None = None
    total_attempts = len(retry_delays) + 1
    for attempt in range(1, total_attempts + 1):
        try:
            response = subprocess.run(
                ["node", "-e", script],
                capture_output=True,
                text=False,
                timeout=120,
                env=environment,
                check=False,
            )
            stdout = decode_output(response.stdout)
            stderr = decode_output(response.stderr)
            record = {
                "attempt": attempt,
                "return_code": response.returncode,
                "stdout": stdout if response.returncode != 0 else "",
                "stderr": stderr,
            }
            attempts.append(record)
            if response.returncode == 0:
                break
            print(json.dumps({"index_ifind_retry": record}, ensure_ascii=False), file=sys.stderr)
        except subprocess.TimeoutExpired as exc:
            record = {
                "attempt": attempt,
                "return_code": None,
                "stdout": decode_output(exc.stdout),
                "stderr": decode_output(exc.stderr) or "Node iFinD call timed out after 120 seconds",
            }
            attempts.append(record)
            print(json.dumps({"index_ifind_retry": record}, ensure_ascii=False), file=sys.stderr)
        write_call_status("retrying" if attempt < total_attempts else "failed", attempts)
        if attempt < total_attempts:
            time.sleep(retry_delays[attempt - 1])
    else:
        response = None

    if response is None or response.returncode != 0:
        detail = attempts[-1]["stderr"] or attempts[-1]["stdout"] or "no Node subprocess output"
        raise RuntimeError(f"iFinD index call failed after {total_attempts} attempts: {detail}")

    outer = json.loads(decode_output(response.stdout))
    answers: list[str] = []
    for item in outer.get("data", {}).get("result", {}).get("content", []):
        item_outer = json.loads(item.get("text", "{}"))
        payload = item_outer.get("data", {})
        inner = json.loads(payload) if isinstance(payload, str) else payload
        answers.append(inner.get("answer", ""))
    answer = "\n".join(answers)
    semantic_errors = ("用户使用工具已超限", "额度已用完", "quota exhausted")
    if any(token.lower() in answer.lower() for token in semantic_errors):
        attempts[-1]["semantic_error"] = answer[:1000]
        write_call_status("semantic_error", attempts)
    else:
        write_call_status("pass", attempts)
    return answer


def parse_tencent_kline(payload: dict, index_code: str) -> list[dict]:
    symbol = TENCENT_SYMBOLS[index_code]
    node = (payload.get("data") or {}).get(symbol) or {}
    rows = node.get("qfqday") or node.get("day") or []
    country, name = NAME_MAP[index_code]
    parsed: list[dict] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 3:
            continue
        try:
            date_value = pd.Timestamp(str(row[0])[:10])
            close = float(row[2])
        except (TypeError, ValueError):
            continue
        if pd.isna(date_value) or not math.isfinite(close) or close <= 0:
            continue
        parsed.append(
            {
                "date": date_value,
                "country": country,
                "index_code": index_code,
                "index_name": name,
                "close": close,
                "change_pct": None,
                "source": "Tencent historical K-line",
            }
        )
    return parsed


def fetch_tencent_indices(
    start: str,
    end: str,
    base: pd.DataFrame,
    retry_delays: tuple[float, ...] = (0.5, 1.0),
) -> tuple[pd.DataFrame, list[dict]]:
    records: list[dict] = []
    attempts: list[dict] = []
    for index_code, symbol in TENCENT_SYMBOLS.items():
        params = {"param": f"{symbol},day,{start},{end},500,qfq"}
        request = Request(
            f"{TENCENT_KLINE_URL}?{urlencode(params)}",
            headers={"User-Agent": "Mozilla/5.0 ETF Catcher/1.0", "Referer": "https://gu.qq.com/"},
        )
        last_error = ""
        for attempt in range(1, len(retry_delays) + 2):
            try:
                with urlopen(request, timeout=20) as response:
                    payload = json.loads(response.read().decode("utf-8", errors="replace"))
                rows = [row for row in parse_tencent_kline(payload, index_code) if pd.Timestamp(start) <= row["date"] <= pd.Timestamp(end)]
                rows = list({row["date"]: row for row in rows}.values())
                if not rows:
                    raise ValueError("Tencent returned no observations in the requested date range")
                attempts.append({"source": "Tencent historical K-line", "index_code": index_code, "attempt": attempt, "rows": len(rows)})
                records.extend(rows)
                break
            except Exception as exc:
                last_error = str(exc)[:500]
                attempts.append({"source": "Tencent historical K-line", "index_code": index_code, "attempt": attempt, "error": last_error})
                if attempt <= len(retry_delays):
                    time.sleep(retry_delays[attempt - 1])
        else:
            attempts.append({"source": "Tencent historical K-line", "index_code": index_code, "error": last_error or "no response"})

    added = pd.DataFrame(records)
    if added.empty:
        return added, attempts
    added = added.sort_values(["index_code", "date"])
    for index_code, positions in added.groupby("index_code").groups.items():
        previous = base.loc[
            (base["index_code"] == index_code) & (pd.to_datetime(base["date"]) < added.loc[positions, "date"].min()),
            ["date", "close"],
        ].sort_values("date")
        previous_close = float(previous.iloc[-1]["close"]) if not previous.empty else None
        for position in positions:
            close = float(added.at[position, "close"])
            if previous_close and previous_close > 0:
                added.at[position, "change_pct"] = (close / previous_close - 1.0) * 100.0
            previous_close = close
    return added, attempts


def load_base() -> pd.DataFrame:
    source = OUTPUT
    if not source.exists():
        raise FileNotFoundError(f"No index seed dataset found: {source}")
    base = pd.read_parquet(source)
    return base[["date", "country", "index_code", "index_name", "close", "change_pct", "source"]].copy()


def write_validation(frame: pd.DataFrame, added: pd.DataFrame, start: str, end: str, sources: list[str] | None = None) -> dict:
    requested_start = pd.Timestamp(start)
    requested_end = pd.Timestamp(end)
    window = frame.loc[frame["date"].between(requested_start, requested_end)]
    counts = {code: int((window["index_code"] == code).sum()) for code in NAME_MAP}
    latest = {
        code: str(group["date"].max().date())
        for code, group in frame.groupby("index_code")
        if code in NAME_MAP
    }
    domestic_at_target = {
        code: bool(((frame["index_code"] == code) & (frame["date"] == requested_end)).any())
        for code in TENCENT_SYMBOLS
    }
    status = "pass" if set(latest) == set(NAME_MAP) and all(domestic_at_target.values()) else "fail"
    report = {
        "status": status,
        "requested_start": start,
        "requested_end": end,
        "added_rows": int(len(added)),
        "window_rows_by_series": counts,
        "latest_by_series": latest,
        "domestic_target_date_present": domestic_at_target,
        "sources_used": sources or sorted(set(added.get("source", pd.Series(dtype=str)).dropna().astype(str))),
        "note": "Only real source observations are stored; no weekend, holiday or interpolated rows are created.",
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
    added, source_attempts = fetch_tencent_indices(args.start, args.end, base)
    target = pd.Timestamp(args.end)
    present = set(added.loc[added.get("date", pd.Series(dtype="datetime64[ns]")) == target, "index_code"]) if not added.empty else set()
    missing = set(TENCENT_SYMBOLS) - present
    if missing:
        answers: list[str] = []
        for subjects in QUERY_BATCHES:
            query = (
                f"分别查询{subjects}在{args.start}至{args.end}逐交易日的收盘点位和涨跌幅，"
                "必须逐日返回证券代码、指数简称、日期、数值和单位；休市日不要返回。"
            )
            answers.append(call_ifind(query))
        fallback = pd.DataFrame(parse_rows("\n".join(answers)))
        if not fallback.empty:
            added = pd.concat([added, fallback], ignore_index=True)
    else:
        write_call_status("skipped_tencent_primary", source_attempts)

    if added.empty:
        write_validation(base, added, args.start, args.end)
        raise RuntimeError("Tencent and iFinD returned no parseable index observations")

    frame = pd.concat([base, added], ignore_index=True)
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.dropna(subset=["date", "index_code", "close"])
    frame = frame.loc[frame["index_code"].isin(NAME_MAP)].copy()
    frame = frame.drop_duplicates(["date", "index_code"], keep="last")
    frame = frame.loc[frame["date"].dt.weekday.lt(5)].sort_values(["index_code", "date"])
    frame["normalized"] = frame.groupby("index_code")["close"].transform(lambda s: s / s.iloc[0] * 100)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(OUTPUT, index=False)
    report = write_validation(frame, added, args.start, args.end)
    print(json.dumps({"rows": len(frame), "added": len(added), **report}, ensure_ascii=False))
    if report["status"] != "pass":
        raise RuntimeError("Domestic index observations are incomplete at the target date")


if __name__ == "__main__":
    main()
