from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FLOW_FIELD = "净流入额"


def parse_number(value: object, unit: object = None) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace("\\t", "").replace(",", "")
    if not text or text in {"-", "--", "None", "null"}:
        return None
    multiplier = 1.0
    for suffix, factor in (
        ("亿元", 1e8), ("亿份", 1e8), ("亿股", 1e8), ("亿", 1e8),
        ("万元", 1e4), ("万份", 1e4), ("万股", 1e4), ("万", 1e4),
    ):
        if text.endswith(suffix):
            multiplier, text = factor, text[: -len(suffix)]
            break
    else:
        normalized_unit = str(unit or "").replace(" ", "")
        if normalized_unit in {"亿元", "亿份", "亿股"}:
            multiplier = 1e8
        elif normalized_unit in {"万元", "万份", "万股"}:
            multiplier = 1e4
    text = text.rstrip("%元份股")
    try:
        result = float(text) * multiplier
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def table_rows(answer: str) -> list[dict[str, str]]:
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


def find_value(row: dict[str, str], prefixes: tuple[str, ...]) -> str | None:
    for key, value in row.items():
        if any(key == prefix or key.startswith(prefix + "（") for prefix in prefixes):
            return value
    return None


def indicator_metadata(job: dict) -> tuple[dict[str, str], dict[str, str]]:
    units: dict[str, str] = {}
    dates: dict[str, str] = {}
    try:
        content = job["result"]["data"]["result"]["content"]
    except (KeyError, TypeError):
        return units, dates
    for item in content:
        try:
            outer = json.loads(item.get("text", "{}"))
            inner = outer.get("data")
            if isinstance(inner, str):
                inner = json.loads(inner)
            for name, params in (inner or {}).get("indicators_params", {}).items():
                if not isinstance(params, dict):
                    continue
                if params.get("单位"):
                    units[name] = str(params["单位"]).strip()
                if params.get("交易日期"):
                    dates[name] = str(params["交易日期"]).strip()
        except (AttributeError, json.JSONDecodeError, TypeError):
            continue
    return units, dates


def extract_records(input_path: Path, target_date: str) -> tuple[dict[str, tuple[float, str]], dict[str, int]]:
    records: dict[str, tuple[float, str]] = {}
    statuses: dict[str, int] = {}
    target_digits = target_date.replace("-", "")
    for line in input_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        job = json.loads(line)
        status = job.get("status", "unknown")
        statuses[status] = statuses.get(status, 0) + 1
        if status != "success":
            continue
        units, dates = indicator_metadata(job)
        metadata_digits = re.sub(r"\D", "", dates.get(FLOW_FIELD, ""))
        job_date = str(job.get("start_date") or "").replace("-", "")
        if metadata_digits and metadata_digits != target_digits:
            continue
        if not metadata_digits and job_date and job_date != target_digits:
            continue
        for row in table_rows(job.get("answer", "")):
            code = (find_value(row, ("证券代码",)) or "").split(".")[0]
            row_digits = re.sub(r"\D", "", find_value(row, ("数据日期", "日期")) or "")
            if row_digits and row_digits != target_digits:
                continue
            raw_value = find_value(row, (FLOW_FIELD,))
            value = parse_number(raw_value, units.get(FLOW_FIELD))
            if code and value is not None:
                records[code] = (value, str(raw_value))
    return records, statuses


def ensure_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS etf_direct_flow_observations (
            trade_date TEXT NOT NULL,
            etf_code TEXT NOT NULL,
            direct_net_flow REAL,
            raw_value TEXT,
            source_unit TEXT,
            source TEXT NOT NULL,
            source_field TEXT NOT NULL,
            available_at TEXT NOT NULL,
            estimated_net_flow REAL,
            selected_net_flow REAL,
            resolution TEXT,
            absolute_difference REAL,
            relative_difference REAL,
            resolved_at TEXT,
            PRIMARY KEY (trade_date, etf_code)
        )
        """
    )


def ingest(database: Path, target_date: str, records: dict[str, tuple[float, str]]) -> None:
    connection = sqlite3.connect(database)
    ensure_table(connection)
    now = datetime.now(timezone.utc).isoformat()
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DELETE FROM etf_direct_flow_observations WHERE trade_date=?", (target_date,))
        for code, (value, raw_value) in records.items():
            connection.execute(
                """INSERT INTO etf_direct_flow_observations(
                       trade_date,etf_code,direct_net_flow,raw_value,source_unit,source,
                       source_field,available_at)
                   VALUES(?,?,?,?,?,'iFinD_get_fund_ownership','净流入额',?)""",
                (target_date, code, value, raw_value, "元", now),
            )
            connection.execute(
                """INSERT INTO etf_daily(
                       trade_date,etf_code,market_source,flow_source,source_field,
                       available_at,data_status,reason_code,schema_version,updated_at)
                   VALUES(?,?,NULL,NULL,'get_fund_ownership|净流入额',?,
                          'flow_only','MARKET_DATA_MISSING_DIRECT_FLOW_AVAILABLE','1.2.0',?)
                   ON CONFLICT(trade_date,etf_code) DO NOTHING""",
                (target_date, code, now, now),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--database", default=str(ROOT / "data" / "etf_flow.sqlite3"))
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    records, statuses = extract_records(Path(args.input), args.date)
    ingest(Path(args.database), args.date, records)
    print(json.dumps({"status": "pass", "date": args.date, "jobs": statuses, "direct_flows": len(records)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
