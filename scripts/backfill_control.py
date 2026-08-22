from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path


MAX_BLOCKING_FAILURES = 3


def load_state(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        payload = {}
    payload.setdefault("schema_version", 1)
    payload.setdefault("dates", {})
    return payload


def save_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporary, path)


def record_failure(
    payload: dict,
    trade_date: str,
    run_id: str,
    error: str,
    attempted_at: str,
    maximum: int = MAX_BLOCKING_FAILURES,
) -> dict:
    entry = payload["dates"].setdefault(trade_date, {})
    if entry.get("last_run_id") != run_id:
        entry["failed_runs"] = int(entry.get("failed_runs") or 0) + 1
    entry.update(
        {
            "last_run_id": run_id,
            "last_attempt_at": attempted_at,
            "last_error": error[:1000],
        }
    )
    entry["quarantined"] = entry["failed_runs"] >= maximum
    return {"trade_date": trade_date, **entry}


def record_success(payload: dict, trade_date: str) -> dict:
    previous = payload["dates"].pop(trade_date, None)
    return {
        "trade_date": trade_date,
        "status": "resolved",
        "previous_failures": int((previous or {}).get("failed_runs") or 0),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("record-failure", "record-success", "status"))
    parser.add_argument("--state", required=True)
    parser.add_argument("--date")
    parser.add_argument("--run-id")
    parser.add_argument("--error", default="")
    parser.add_argument("--maximum", type=int, default=MAX_BLOCKING_FAILURES)
    args = parser.parse_args()

    state_path = Path(args.state)
    payload = load_state(state_path)
    if args.command == "record-failure":
        if not args.date or not args.run_id:
            parser.error("record-failure requires --date and --run-id")
        result = record_failure(
            payload,
            args.date,
            args.run_id,
            args.error,
            datetime.now().astimezone().isoformat(),
            args.maximum,
        )
        save_state(state_path, payload)
    elif args.command == "record-success":
        if not args.date:
            parser.error("record-success requires --date")
        result = record_success(payload, args.date)
        save_state(state_path, payload)
    else:
        result = payload
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()

