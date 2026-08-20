from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIELD_CODE = "\u8bc1\u5238\u4ee3\u7801"
FIELD_DATE = "\u65e5\u671f"
FIELD_SHARE = "\u57fa\u91d1\u4efd\u989d"
FIELD_SCALE = "\u57fa\u91d1\u89c4\u6a21"
FIELD_OPEN = "\u5f00\u76d8\u4ef7"
FIELD_HIGH = "\u6700\u9ad8\u4ef7"
FIELD_LOW = "\u6700\u4f4e\u4ef7"
FIELD_CLOSE = "\u6536\u76d8\u4ef7"
FIELD_CHANGE = "\u6da8\u8dcc\u5e45"
FIELD_VOLUME = "\u6210\u4ea4\u91cf"
FIELD_AMOUNT = "\u6210\u4ea4\u989d"


def number(value):
    if value is None:
        return None
    text = str(value).strip().replace("\\t", "").replace(",", "")
    if not text or text in {"-", "--", "None", "null"}:
        return None
    multiplier = 1.0
    if text.endswith("\u4ebf"):
        multiplier, text = 1e8, text[:-1]
    elif text.endswith("\u4e07"):
        multiplier, text = 1e4, text[:-1]
    text = text.rstrip("%\u5143\u4efd\u80a1")
    try:
        result = float(text) * multiplier
    except ValueError:
        return None
    return result if math.isfinite(result) else None

def indicator_units(job):
    try:
        content = job["result"]["data"]["result"]["content"]
    except (KeyError, TypeError):
        return {}
    units = {}
    for item in content:
        try:
            outer = json.loads(item.get("text", "{}"))
            inner = outer.get("data")
            if isinstance(inner, str):
                inner = json.loads(inner)
            for name, params in (inner or {}).get("indicators_params", {}).items():
                if isinstance(params, dict) and params.get("单位"):
                    units[name] = str(params["单位"]).strip()
        except (AttributeError, json.JSONDecodeError, TypeError):
            continue
    return units


def number_with_unit(value, unit):
    parsed = number(value)
    if parsed is None:
        return None
    raw = str(value).strip().replace("\\t", "").replace(",", "")
    if raw.endswith(("万", "亿", "万元", "亿元", "万份", "亿份", "万股", "亿股")):
        return parsed
    normalized = str(unit or "").replace(" ", "")
    if normalized in {"亿元", "亿份", "亿股"}:
        return parsed * 1e8
    if normalized in {"万元", "万份", "万股"}:
        return parsed * 1e4
    return parsed


def markdown_rows(answer):
    lines = [line.strip() for line in answer.splitlines() if line.strip().startswith("|")]
    if len(lines) < 3:
        return []
    headers = [cell.strip() for cell in lines[0].strip("|").split("|")]
    output = []
    for line in lines[2:]:
        values = [cell.strip() for cell in line.strip("|").split("|")]
        if len(values) == len(headers):
            output.append(dict(zip(headers, values)))
    return output


def field(row, prefix):
    for key, value in row.items():
        if key == prefix or key.startswith(prefix + "\uff08"):
            return value
    return None


def extract_records(input_path: Path, target_date: str):
    records = {}
    statuses = {}
    for line in input_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        job = json.loads(line)
        status = job.get("status", "unknown")
        statuses[status] = statuses.get(status, 0) + 1
        if status != "success":
            continue
        units = indicator_units(job)
        for row in markdown_rows(job.get("answer", "")):
            code = (field(row, FIELD_CODE) or "").split(".")[0]
            digits = re.sub(r"\D", "", field(row, FIELD_DATE) or "")
            if not code or len(digits) != 8:
                continue
            trade_date = f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
            if trade_date != target_date:
                continue
            item = {
                "fund_share": number_with_unit(field(row, FIELD_SHARE), units.get(FIELD_SHARE)),
                "fund_scale": number_with_unit(field(row, FIELD_SCALE), units.get(FIELD_SCALE)),
                "open": number_with_unit(field(row, FIELD_OPEN), units.get(FIELD_OPEN)),
                "high": number_with_unit(field(row, FIELD_HIGH), units.get(FIELD_HIGH)),
                "low": number_with_unit(field(row, FIELD_LOW), units.get(FIELD_LOW)),
                "close": number_with_unit(field(row, FIELD_CLOSE), units.get(FIELD_CLOSE)),
                "pct_change": number_with_unit(field(row, FIELD_CHANGE), units.get(FIELD_CHANGE)),
                "volume": number_with_unit(field(row, FIELD_VOLUME), units.get(FIELD_VOLUME)),
                "amount": number_with_unit(field(row, FIELD_AMOUNT), units.get(FIELD_AMOUNT)),
            }
            if item["close"] is not None:
                records[code] = item
    return records, statuses


def ingest(database: Path, target_date: str, records):
    connection = sqlite3.connect(database)
    now = datetime.now(timezone.utc).isoformat()
    sql = """
        INSERT INTO etf_daily(
            trade_date,etf_code,fund_share,fund_scale,open,high,low,close,
            pct_change,volume,amount,net_flow,net_inflow,net_outflow,
            market_source,flow_source,source_field,available_at,data_status,
            reason_code,schema_version,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,'iFinD',NULL,
            'fund_share|fund_scale|ohlcv',?,'market_only',
            'PENDING_SHARE_CHANGE_ESTIMATE','1.2.0',?)
        ON CONFLICT(trade_date,etf_code) DO UPDATE SET
            fund_share=COALESCE(excluded.fund_share,fund_share),
            fund_scale=COALESCE(excluded.fund_scale,fund_scale),
            open=COALESCE(excluded.open,open),
            high=COALESCE(excluded.high,high),
            low=COALESCE(excluded.low,low),
            close=COALESCE(excluded.close,close),
            pct_change=COALESCE(excluded.pct_change,pct_change),
            volume=COALESCE(excluded.volume,volume),
            amount=COALESCE(excluded.amount,amount),
            net_flow=NULL,net_inflow=NULL,net_outflow=NULL,
            market_source='iFinD',flow_source=NULL,
            source_field=excluded.source_field,
            available_at=excluded.available_at,
            data_status='market_only',
            reason_code='PENDING_SHARE_CHANGE_ESTIMATE',
            updated_at=excluded.updated_at
    """
    for code, item in records.items():
        connection.execute(
            sql,
            (
                target_date, code, item["fund_share"], item["fund_scale"],
                item["open"], item["high"], item["low"], item["close"],
                item["pct_change"], item["volume"], item["amount"],
                None, None, None, now, now,
            ),
        )
    connection.execute(
        """UPDATE etf_daily AS current
           SET pct_change=(current.close/(
               SELECT previous.close FROM etf_daily AS previous
               WHERE previous.etf_code=current.etf_code
                 AND previous.trade_date<current.trade_date
                 AND previous.close IS NOT NULL
               ORDER BY previous.trade_date DESC LIMIT 1
           )-1.0)*100.0
           WHERE current.trade_date=? AND current.close IS NOT NULL""",
        (target_date,),
    )
    connection.commit()
    validation = connection.execute(
        "SELECT COUNT(*),COUNT(close),COUNT(fund_share) FROM etf_daily WHERE trade_date=?",
        (target_date,),
    ).fetchone()
    connection.close()
    return validation


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--database", default=str(ROOT / "data" / "etf_flow.sqlite3"))
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    records, statuses = extract_records(Path(args.input), args.date)
    if not records:
        raise RuntimeError("No valid ETF market rows parsed from iFinD results")
    validation = ingest(Path(args.database), args.date, records)
    print(json.dumps({"status": "pass", "date": args.date, "jobs": statuses, "parsed": len(records), "validation": validation}, ensure_ascii=False))


if __name__ == "__main__":
    main()
