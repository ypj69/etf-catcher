from __future__ import annotations

import argparse
import csv
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from etf_classification import classify_etf
    from universe_paths import BASELINE_UNIVERSE, LOCAL_UNIVERSE, ROOT
except ModuleNotFoundError:  # imported as scripts.maintain_etf_universe by tests/tools
    from scripts.etf_classification import classify_etf
    from scripts.universe_paths import BASELINE_UNIVERSE, LOCAL_UNIVERSE, ROOT


SOURCE_URL = "https://fund.eastmoney.com/js/fundcode_search.js"
SOURCE_NAME = "eastmoney_fundcode_search"
SCHEMA_VERSION = "1.2.0"
UNIVERSE_FIELDS = (
    "etf_code", "exchange", "etf_name", "source_fund_type", "asset_class",
    "category_l1", "category_l2", "classification_rule",
    "classification_confidence", "review_status", "tracking_index_code",
    "tracking_index_name", "enabled", "history_start", "universe_source",
)


@dataclass(frozen=True)
class SourceEtf:
    code: str
    name: str
    fund_type: str


def local_now() -> datetime:
    return datetime.now().astimezone()


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding=encoding, newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def ensure_local_universe(local_path: Path, baseline_path: Path) -> None:
    if local_path.exists():
        return
    if not baseline_path.exists():
        raise FileNotFoundError(f"bundled ETF universe is missing: {baseline_path}")
    local_path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{local_path.name}.", suffix=".tmp", dir=local_path.parent)
    os.close(handle)
    try:
        shutil.copyfile(baseline_path, temporary)
        os.replace(temporary, local_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


def decode_source(raw: bytes) -> str:
    errors: list[str] = []
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError as exc:
            errors.append(f"{encoding}: {exc}")
            continue
        if "\ufffd" not in text and "var r" in text:
            return text
        errors.append(f"{encoding}: invalid characters or marker")
    raise ValueError("ETF source encoding is invalid: " + "; ".join(errors))


def fetch_source(url: str = SOURCE_URL, attempts: int = 3) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 ETF-Catcher-Universe-Maintenance/1.0.4"},
    )
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    raise RuntimeError(f"ETF universe source unavailable after {attempts} attempts: {last_error}")


def parse_source(raw: bytes) -> dict[str, SourceEtf]:
    text = decode_source(raw)
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        raise ValueError("ETF universe source does not contain a JSON array")
    payload = json.loads(text[start : end + 1])
    candidates: dict[str, SourceEtf] = {}
    for item in payload:
        if not isinstance(item, list) or len(item) < 4:
            continue
        code, name, fund_type = str(item[0]).strip(), str(item[2]).strip(), str(item[3]).strip()
        normalized = name.upper().replace("ＥＴＦ", "ETF")
        if len(code) == 6 and code.isdigit() and code.startswith(("1", "5")) and "ETF" in normalized and "联接" not in name:
            candidates[code] = SourceEtf(code, name, fund_type)
    return candidates


def load_universe(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = set(UNIVERSE_FIELDS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"universe CSV is missing fields: {sorted(missing)}")
        rows = [{field: (row.get(field) or "").strip() for field in UNIVERSE_FIELDS} for row in reader]
    codes = [row["etf_code"] for row in rows]
    if len(codes) != len(set(codes)):
        raise ValueError("universe CSV contains duplicate ETF codes")
    return rows


def validate_snapshot(candidates: dict[str, SourceEtf], rows: list[dict[str, str]]) -> None:
    enabled = {row["etf_code"] for row in rows if row["enabled"] == "1"}
    minimum_count = max(1000, int(len(enabled) * 0.90))
    minimum_overlap = int(len(enabled) * 0.90)
    overlap = len(enabled & set(candidates))
    if len(candidates) < minimum_count:
        raise ValueError(f"source collapse guard: candidates={len(candidates)}, required>={minimum_count}")
    if overlap < minimum_overlap:
        raise ValueError(f"source overlap guard: overlap={overlap}, required>={minimum_overlap}")


def due_for_run(state: dict[str, Any], as_of: date, minimum_days: int) -> bool:
    try:
        return as_of >= date.fromisoformat(str(state["last_success_date"])) + timedelta(days=minimum_days)
    except (KeyError, TypeError, ValueError):
        return True


def plan_changes(
    rows: list[dict[str, str]], candidates: dict[str, SourceEtf], state: dict[str, Any],
    as_of: date, missing_threshold: int,
) -> tuple[list[dict[str, str]], dict[str, Any], dict[str, list[dict[str, Any]]]]:
    by_code = {row["etf_code"]: dict(row) for row in rows}
    missing_state = dict(state.get("consecutive_missing") or {})
    disabled_state = dict(state.get("maintenance_disabled") or {})
    events: dict[str, list[dict[str, Any]]] = {
        key: [] for key in ("added_enabled", "added_review", "renamed", "promoted", "reactivated", "disabled", "pending_missing")
    }
    for code, source in candidates.items():
        classification = classify_etf(source.name, source.fund_type)
        existing = by_code.get(code)
        missing_state.pop(code, None)
        if existing is None:
            enabled = classification.classification_confidence == "high"
            row = {
                "etf_code": code, "exchange": "SH" if code.startswith("5") else "SZ",
                "etf_name": source.name, "source_fund_type": source.fund_type,
                **classification.as_dict(), "tracking_index_code": "", "tracking_index_name": "",
                "enabled": "1" if enabled else "0", "history_start": as_of.isoformat(),
                "universe_source": SOURCE_NAME,
            }
            by_code[code] = row
            bucket = "added_enabled" if enabled else "added_review"
            events[bucket].append({"etf_code": code, "etf_name": source.name, "category_l2": row["category_l2"]})
            continue
        old_name = existing["etf_name"]
        existing["source_fund_type"] = source.fund_type or existing["source_fund_type"]
        existing["universe_source"] = SOURCE_NAME
        if old_name != source.name:
            existing["etf_name"] = source.name
            events["renamed"].append({"etf_code": code, "old_name": old_name, "new_name": source.name})
            if classification.classification_confidence == "high":
                existing.update(classification.as_dict())
            else:
                existing.update({"classification_rule": "rename_requires_review", "classification_confidence": "low", "review_status": "needs_review"})
        if code in disabled_state and classification.classification_confidence == "high":
            existing["enabled"] = "1"
            existing.update(classification.as_dict())
            disabled_state.pop(code, None)
            events["reactivated"].append({"etf_code": code, "etf_name": source.name})
        elif existing["enabled"] == "0" and existing["review_status"] == "needs_review" and classification.classification_confidence == "high":
            existing["enabled"] = "1"
            existing.update(classification.as_dict())
            events["promoted"].append({"etf_code": code, "etf_name": source.name})

    for code, existing in by_code.items():
        if existing["enabled"] != "1" or code in candidates:
            continue
        prior = missing_state.get(code) or {}
        count = int(prior.get("count") or 0) + 1
        record = {"count": count, "first_seen": prior.get("first_seen") or as_of.isoformat(), "last_seen": as_of.isoformat()}
        if count >= missing_threshold:
            existing["enabled"] = "0"
            existing["review_status"] = "inactive_confirmed"
            disabled_state[code] = {**record, "disabled_on": as_of.isoformat()}
            missing_state.pop(code, None)
            events["disabled"].append({"etf_code": code, "etf_name": existing["etf_name"], "misses": count})
        else:
            missing_state[code] = record
            events["pending_missing"].append({"etf_code": code, "etf_name": existing["etf_name"], "misses": count})
    next_state = {
        "schema_version": 1, "last_success_date": as_of.isoformat(), "last_success_at": local_now().isoformat(),
        "consecutive_missing": missing_state, "maintenance_disabled": disabled_state,
    }
    return sorted(by_code.values(), key=lambda row: row["etf_code"]), next_state, events


def render_csv(rows: list[dict[str, str]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=UNIVERSE_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows({field: row.get(field, "") for field in UNIVERSE_FIELDS} for row in rows)
    return output.getvalue()


def sync_database(connection: sqlite3.Connection, rows: list[dict[str, str]], as_of: date, inactive_dates: dict[str, str]) -> None:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(etf_master)")}
    required = {"etf_code", "exchange", "etf_name", "asset_class", "category_l1", "category_l2", "source_fund_type", "classification_rule", "classification_confidence", "review_status", "tracking_index_code", "tracking_index_name", "active_from", "active_to", "enabled", "source", "schema_version", "updated_at"}
    if not required.issubset(columns):
        raise ValueError(f"SQLite etf_master schema is incompatible; missing={sorted(required - columns)}")
    now = local_now().isoformat()
    sql = """
        INSERT INTO etf_master(etf_code,exchange,etf_name,asset_class,category_l1,category_l2,source_fund_type,classification_rule,classification_confidence,review_status,tracking_index_code,tracking_index_name,active_from,active_to,enabled,source,schema_version,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(etf_code) DO UPDATE SET exchange=excluded.exchange,etf_name=excluded.etf_name,asset_class=excluded.asset_class,category_l1=excluded.category_l1,category_l2=excluded.category_l2,source_fund_type=excluded.source_fund_type,classification_rule=excluded.classification_rule,classification_confidence=excluded.classification_confidence,review_status=excluded.review_status,tracking_index_code=COALESCE(NULLIF(excluded.tracking_index_code,''),etf_master.tracking_index_code),tracking_index_name=COALESCE(NULLIF(excluded.tracking_index_name,''),etf_master.tracking_index_name),active_from=COALESCE(etf_master.active_from,excluded.active_from),active_to=CASE WHEN excluded.enabled=1 THEN NULL WHEN excluded.active_to IS NOT NULL THEN excluded.active_to ELSE etf_master.active_to END,enabled=excluded.enabled,source=excluded.source,schema_version=excluded.schema_version,updated_at=excluded.updated_at
    """
    connection.executemany(sql, [(
        row["etf_code"], row["exchange"], row["etf_name"], row["asset_class"], row["category_l1"], row["category_l2"],
        row["source_fund_type"], row["classification_rule"], row["classification_confidence"], row["review_status"],
        row["tracking_index_code"], row["tracking_index_name"], row["history_start"] or as_of.isoformat(),
        inactive_dates.get(row["etf_code"]), int(row["enabled"]), SOURCE_NAME, SCHEMA_VERSION, now,
    ) for row in rows])


def apply_atomically(universe: Path, database: Path, rows: list[dict[str, str]], as_of: date, inactive_dates: dict[str, str]) -> None:
    original = universe.read_bytes()
    handle, temporary = tempfile.mkstemp(prefix=f".{universe.name}.", suffix=".tmp", dir=universe.parent)
    replaced = False
    connection = sqlite3.connect(database, timeout=30)
    try:
        with os.fdopen(handle, "w", encoding="utf-8-sig", newline="") as stream:
            stream.write(render_csv(rows))
            stream.flush()
            os.fsync(stream.fileno())
        connection.execute("BEGIN IMMEDIATE")
        sync_database(connection, rows, as_of, inactive_dates)
        os.replace(temporary, universe)
        replaced = True
        connection.commit()
    except Exception:
        connection.rollback()
        if replaced:
            restore_handle, restore_path = tempfile.mkstemp(prefix=f".{universe.name}.restore.", suffix=".tmp", dir=universe.parent)
            with os.fdopen(restore_handle, "wb") as stream:
                stream.write(original)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(restore_path, universe)
        raise
    finally:
        connection.close()
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_report(report: Path, history: Path, payload: dict[str, Any], append: bool = True) -> None:
    atomic_write_text(report, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    if append:
        history.parent.mkdir(parents=True, exist_ok=True)
        with history.open("a", encoding="utf-8", newline="") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Weekly ETF universe discovery and lifecycle maintenance")
    parser.add_argument("--universe", type=Path, default=LOCAL_UNIVERSE)
    parser.add_argument("--baseline-universe", type=Path, default=BASELINE_UNIVERSE)
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "etf_catcher.sqlite3")
    parser.add_argument("--state", type=Path, default=ROOT / "runtime" / "etf_universe_maintenance_state.json")
    parser.add_argument("--report", type=Path, default=ROOT / "runtime" / "etf_universe_maintenance.json")
    parser.add_argument("--history", type=Path, default=ROOT / "runtime" / "etf_universe_maintenance_history.jsonl")
    parser.add_argument("--source-file", type=Path)
    parser.add_argument("--source-url", default=SOURCE_URL)
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--minimum-days", type=int, default=7)
    parser.add_argument("--missing-threshold", type=int, default=3)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--nonblocking", action="store_true")
    args = parser.parse_args()
    as_of = date.fromisoformat(args.as_of)
    state = load_json(args.state, {})
    try:
        ensure_local_universe(args.universe, args.baseline_universe)
        if not args.force and not due_for_run(state, as_of, args.minimum_days):
            payload = {"status": "skipped_not_due", "checked_at": local_now().isoformat(), "as_of": as_of.isoformat(), "last_success_date": state.get("last_success_date"), "minimum_days": args.minimum_days}
            write_report(args.report, args.history, payload, append=False)
            print(json.dumps(payload, ensure_ascii=False))
            return 0
        rows = load_universe(args.universe)
        raw = args.source_file.read_bytes() if args.source_file else fetch_source(args.source_url)
        candidates = parse_source(raw)
        validate_snapshot(candidates, rows)
        next_rows, next_state, events = plan_changes(rows, candidates, state, as_of, args.missing_threshold)
        inactive_dates = {code: str(record.get("disabled_on") or as_of.isoformat()) for code, record in next_state["maintenance_disabled"].items()}
        if not args.dry_run:
            apply_atomically(args.universe, args.database, next_rows, as_of, inactive_dates)
            atomic_write_text(args.state, json.dumps(next_state, ensure_ascii=False, indent=2) + "\n")
        payload = {
            "status": "dry_run" if args.dry_run else "pass", "checked_at": local_now().isoformat(), "as_of": as_of.isoformat(),
            "source": str(args.source_file) if args.source_file else args.source_url, "source_count": len(candidates),
            "universe_before": len(rows), "universe_after": len(next_rows),
            "enabled_before": sum(row["enabled"] == "1" for row in rows), "enabled_after": sum(row["enabled"] == "1" for row in next_rows), "events": events,
        }
        write_report(args.report, args.history, payload, append=not args.dry_run)
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    except Exception as exc:
        payload = {"status": "warning_source_retained" if args.nonblocking else "failed", "checked_at": local_now().isoformat(), "as_of": as_of.isoformat(), "detail": str(exc), "action": "kept_last_successful_universe"}
        write_report(args.report, args.history, payload)
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
        return 0 if args.nonblocking else 1


if __name__ == "__main__":
    raise SystemExit(main())
