from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from universe_paths import active_universe_path
from ifind_native_config import load_credentials


ROOT = Path(__file__).resolve().parents[1]
INDICATORS = "ths_fund_shares_fund;ths_fund_scale_fund;ths_netcashflow_fund"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def has_table_rows(answer: object) -> bool:
    lines = [line for line in str(answer or "").splitlines() if line.strip().startswith("|")]
    return len(lines) >= 3 and "查询结果为空" not in str(answer or "")


def load_universe() -> tuple[dict[str, str], dict[str, str]]:
    exchanges: dict[str, str] = {}
    names: dict[str, str] = {}
    with active_universe_path().open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            code = str(row.get("etf_code") or "").strip()
            if not code:
                continue
            exchanges[code] = str(row.get("exchange") or "").strip()
            names[code] = str(row.get("etf_name") or "").strip()
    return exchanges, names


def full_codes(job: dict, exchanges: dict[str, str]) -> list[str]:
    supplied = [str(value).strip() for value in job.get("ths_codes") or [] if str(value).strip()]
    if supplied:
        return supplied
    output = []
    for value in job.get("codes") or []:
        code = str(value).split(".")[0].strip()
        exchange = exchanges.get(code)
        if not exchange:
            raise ValueError(f"Missing exchange for ETF {code}")
        output.append(f"{code}.{exchange}")
    return output


def scalar(table: dict, indicator: str) -> object:
    value = table.get(indicator)
    if isinstance(value, list):
        return value[0] if value else None
    return value


def display_number(value: object) -> str:
    if value is None:
        return "--"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"
    if not math.isfinite(number):
        return "--"
    return format(number, ".15g")


def markdown_answer(tables: object, requested_codes: list[str], target_date: str, names: dict[str, str]) -> tuple[str, int]:
    rows = tables if isinstance(tables, list) else []
    by_code = {
        str(item.get("thscode") or "").strip(): item
        for item in rows
        if isinstance(item, dict) and str(item.get("thscode") or "").strip()
    }
    lines = [
        "| 证券代码 | 证券简称 | 日期 | 基金份额（单位：份） | 基金规模（单位：元） | 净流入额（单位：元） |",
        "|---|---|---|---:|---:|---:|",
    ]
    for thscode in requested_codes:
        item = by_code.get(thscode, {})
        code = thscode.split(".")[0]
        table = item.get("table") if isinstance(item.get("table"), dict) else {}
        name = names.get(code, "").replace("|", "\\|")
        lines.append(
            "| "
            + " | ".join(
                (
                    thscode,
                    name,
                    target_date,
                    display_number(scalar(table, "ths_fund_shares_fund")),
                    display_number(scalar(table, "ths_fund_scale_fund")),
                    display_number(scalar(table, "ths_netcashflow_fund")),
                )
            )
            + " |"
        )
    # A rendered placeholder row is not evidence of successful data collection.
    available = sum(
        any(display_number(scalar((by_code.get(code, {}).get("table") or {}), field)) != "--"
            for field in INDICATORS.split(";"))
        for code in requested_codes
    )
    return "\n".join(lines), available


def completed_jobs(output: Path) -> set[str]:
    completed: set[str] = set()
    if not output.exists():
        return completed
    for line in output.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            prior = json.loads(line)
        except json.JSONDecodeError:
            continue
        if prior.get("status") == "success" and has_table_rows(prior.get("answer")):
            completed.add(str(prior.get("job_id") or ""))
    return completed


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch ETF flow collection through the native iFinD Python API")
    parser.add_argument("--jobs", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--attempts", type=int, default=5)
    parser.add_argument("--pause-seconds", type=float, default=0.5)
    parser.add_argument("--max-jobs", type=int)
    parser.add_argument("--sdk-path", default=os.environ.get("IFIND_SDK_DIR", ""))
    args = parser.parse_args()

    jobs = json.loads(Path(args.jobs).read_text(encoding="utf-8-sig"))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    completed = completed_jobs(output)
    pending = [job for job in jobs if str(job.get("job_id") or "") not in completed]
    if args.max_jobs is not None:
        pending = pending[: max(0, args.max_jobs)]
    if not pending:
        print(json.dumps({"status": "pass", "processed": 0, "completed_before": len(completed)}))
        return
    username, password = load_credentials()
    if args.sdk_path:
        sys.path.insert(0, str(Path(args.sdk_path).resolve()))
    try:
        from iFinDPy import THS_BD, THS_iFinDLogin, THS_iFinDLogout
    except (ImportError, OSError):
        raise RuntimeError("iFinD native SDK unavailable. Install the official SDK into this project's .venv; see README.") from None
    exchanges, names = load_universe()
    max_attempts = min(5, max(1, args.attempts))

    login_code = THS_iFinDLogin(username, password)
    if login_code not in (0, -201):
        raise RuntimeError(f"iFinD Python API login failed with code {login_code}")
    processed = 0
    try:
        with output.open("a", encoding="utf-8", newline="") as stream:
            for job in pending:
                started_at = now_iso()
                record: dict = {}
                codes = full_codes(job, exchanges)
                target_date = str(job.get("start_date") or job.get("end_date") or "")
                params = ";".join((target_date, target_date, target_date))
                for attempt in range(1, max_attempts + 1):
                    result = None
                    try:
                        result = THS_BD(codes, INDICATORS, params, "format:list")
                        if result.errorcode != 0:
                            raise RuntimeError(f"iFinD THS_BD error code {result.errorcode}")
                        answer, available_row_count = markdown_answer(result.data, codes, target_date, names)
                        status = "success" if available_row_count > 0 else "empty"
                        record = {
                            **job,
                            "provider": "iFinD_Python_API",
                            "api": "THS_BD",
                            "indicators": INDICATORS.split(";"),
                            "attempt": attempt,
                            "answer": answer,
                            "data_vol": int(result.dataVol or 0),
                            "row_count": len(codes),
                            "available_row_count": available_row_count,
                            "started_at": started_at,
                            "finished_at": now_iso(),
                            "status": status,
                        }
                        if status == "success":
                            break
                        raise RuntimeError("iFinD returned no renderable result rows")
                    except Exception as exc:
                        record = {
                            **job,
                            "provider": "iFinD_Python_API",
                            "api": "THS_BD",
                            "attempt": attempt,
                            "error": f"Native API collection failed ({type(exc).__name__}); check SDK permissions and data availability",
                            "error_code": getattr(result, "errorcode", None),
                            "started_at": started_at,
                            "finished_at": now_iso(),
                            "status": "error",
                        }
                        if attempt < max_attempts:
                            delay = min(30.0, 3.0 * (2 ** (attempt - 1)))
                            # Windows PowerShell 5 promotes native stderr to a
                            # terminating NativeCommandError when the parent
                            # pipeline uses ErrorActionPreference=Stop. A retry
                            # notice is progress, not a terminal failure.
                            print(json.dumps({"job_id": job.get("job_id"), "attempt": attempt, "retry_in_seconds": delay}))
                            time.sleep(delay)
                stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                stream.flush()
                processed += 1
                done = len(completed) + processed
                if done % 10 == 0 or processed == len(pending):
                    print(json.dumps({"done": done, "total": len(jobs), "provider": "iFinD_Python_API"}, ensure_ascii=False))
                if record.get("status") != "success":
                    raise RuntimeError(f"iFinD collection failed for {job.get('job_id')}")
                if args.pause_seconds > 0:
                    time.sleep(args.pause_seconds)
    finally:
        THS_iFinDLogout()

    print(json.dumps({"status": "pass", "completed_before": len(completed), "processed": processed, "total": len(jobs), "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Never serialize arbitrary SDK exception text (may contain account data).
        print(json.dumps({"status": "fail", "error_type": type(exc).__name__,
                          "guidance": "Check native SDK setup, account permissions/quota and runtime/ifind_collection_route_status.json; see README."}))
        raise SystemExit(1)
