from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
TENCENT_URL = "https://qt.gtimg.cn/q="
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ETF Catcher/1.0.3"
_LOCAL = threading.local()


def secid(code: str) -> str:
    return f"{1 if code.startswith('5') else 0}.{code}"


def session() -> requests.Session:
    current = getattr(_LOCAL, "session", None)
    if current is None:
        current = requests.Session()
        current.headers.update({"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"})
        _LOCAL.session = current
    return current


def fetch_market(code: str, target_date: str, retries: int = 3) -> dict[str, float] | None:
    compact = target_date.replace("-", "")
    params = {
        "secid": secid(code), "klt": 101, "fqt": 0,
        "fields1": "f1,f2,f3,f4,f5,f6", "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "beg": compact, "end": compact, "lmt": 1,
    }
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = session().get(URL, params=params, timeout=20)
            response.raise_for_status()
            lines = ((response.json().get("data") or {}).get("klines") or [])
            if not lines:
                return None
            values = lines[-1].split(",")
            if len(values) < 11 or values[0] != target_date:
                return None
            close = float(values[2])
            amount = float(values[6])
            if not math.isfinite(close) or close <= 0 or not math.isfinite(amount) or amount < 0:
                return None
            return {"close": close, "amount": amount}
        except Exception as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(0.4 * (attempt + 1))
    raise RuntimeError(str(last_error) if last_error else "market request failed")


def tencent_symbol(code: str) -> str:
    return ("sh" if code.startswith("5") else "sz") + code


def parse_tencent_quotes(text: str, target_date: str) -> dict[str, dict[str, float | str]]:
    expected_date = target_date.replace("-", "")
    records: dict[str, dict[str, float | str]] = {}
    for line in text.split(";"):
        if '="' not in line:
            continue
        values = line.split('"', 2)[1].split("~")
        if len(values) < 38:
            continue
        code = values[2]
        quote_date = values[30][:8]
        try:
            close = float(values[3])
            amount = float(values[37]) * 10_000.0
        except (TypeError, ValueError):
            continue
        if quote_date != expected_date or close <= 0 or amount < 0:
            continue
        records[code] = {
            "close": close,
            "amount": amount,
            "market_source": "tencent_quote",
        }
    return records


def fetch_tencent_market(
    codes: list[str], target_date: str, batch_size: int = 50, retries: int = 3
) -> tuple[dict[str, dict[str, float | str]], dict[str, str]]:
    records: dict[str, dict[str, float | str]] = {}
    errors: dict[str, str] = {}
    current = session()
    current.headers.update({"Referer": "https://gu.qq.com/"})
    for offset in range(0, len(codes), batch_size):
        batch = codes[offset : offset + batch_size]
        last_error: Exception | None = None
        text = ""
        for attempt in range(retries):
            try:
                response = current.get(
                    TENCENT_URL + ",".join(tencent_symbol(code) for code in batch), timeout=20
                )
                response.raise_for_status()
                text = response.content.decode("gbk", errors="ignore")
                break
            except Exception as exc:
                last_error = exc
                if attempt + 1 < retries:
                    time.sleep(0.4 * (attempt + 1))
        parsed = parse_tencent_quotes(text, target_date) if text else {}
        records.update(parsed)
        for code in batch:
            if code not in parsed:
                errors[code] = str(last_error)[:300] if last_error else "target date unavailable"
        time.sleep(0.08)
    return records, errors


def enabled_codes() -> list[str]:
    with (ROOT / "config" / "etf_universe.csv").open(encoding="utf-8-sig", newline="") as handle:
        return [row["etf_code"] for row in csv.DictReader(handle) if row.get("enabled") == "1"]


def collect(codes: list[str], target_date: str, workers: int) -> tuple[dict[str, dict[str, float | str]], dict[str, str]]:
    records, errors = fetch_tencent_market(codes, target_date)
    required = max(1, math.ceil(len(codes) * 0.95))
    if len(records) >= required:
        return records, errors

    # Historical/backfill dates may not match Tencent's latest quote timestamp.
    # Fall back to Eastmoney only when Tencent cannot meet the publication gate,
    # and keep it serial to avoid aggravating push2his IP rate limiting.
    missing = [code for code in codes if code not in records]
    for code in missing:
        try:
            row = fetch_market(code, target_date)
            if row is not None:
                records[code] = {**row, "market_source": "eastmoney_kline"}
                errors.pop(code, None)
            else:
                errors[code] = "target date unavailable"
        except Exception as exc:
            errors[code] = str(exc)[:300]
        time.sleep(1.1)
    return records, errors


def ingest(database: Path, target_date: str, records: dict[str, dict[str, float]]) -> None:
    connection = sqlite3.connect(database)
    now = datetime.now(timezone.utc).isoformat()
    sql = """
        INSERT INTO etf_daily(
            trade_date,etf_code,close,amount,market_source,source_field,
            available_at,data_status,reason_code,schema_version,updated_at
        ) VALUES(?,?,?,?,?,'close|amount',?,'market_only',
                 'PENDING_OWNERSHIP_AND_FLOW','1.2.0',?)
        ON CONFLICT(trade_date,etf_code) DO UPDATE SET
            close=COALESCE(etf_daily.close,excluded.close),
            amount=COALESCE(etf_daily.amount,excluded.amount),
            market_source=CASE WHEN etf_daily.close IS NULL OR etf_daily.amount IS NULL
                               THEN excluded.market_source ELSE etf_daily.market_source END,
            source_field=CASE WHEN etf_daily.close IS NULL OR etf_daily.amount IS NULL
                              THEN excluded.source_field ELSE etf_daily.source_field END,
            available_at=CASE WHEN etf_daily.close IS NULL OR etf_daily.amount IS NULL
                              THEN excluded.available_at ELSE etf_daily.available_at END,
            updated_at=CASE WHEN etf_daily.close IS NULL OR etf_daily.amount IS NULL
                            THEN excluded.updated_at ELSE etf_daily.updated_at END
    """
    try:
        connection.execute("BEGIN IMMEDIATE")
        for code, row in records.items():
            connection.execute(
                sql,
                (
                    target_date,
                    code,
                    row["close"],
                    row["amount"],
                    row.get("market_source", "eastmoney_kline"),
                    now,
                    now,
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
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default=str(ROOT / "data" / "etf_flow.sqlite3"))
    parser.add_argument("--date", required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--minimum-coverage", type=float, default=0.95)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    codes = enabled_codes()
    if args.limit:
        codes = codes[: args.limit]
    records, errors = collect(codes, args.date, args.workers)
    required = max(1, math.ceil(len(codes) * args.minimum_coverage))
    if len(records) < required:
        raise RuntimeError(f"Market source coverage {len(records)}/{len(codes)} is below required {required}; sample errors: {dict(list(errors.items())[:10])}")
    ingest(Path(args.database), args.date, records)
    print(json.dumps({"status": "pass", "date": args.date, "requested": len(codes), "market_rows": len(records), "errors": len(errors), "error_sample": dict(list(errors.items())[:10])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
