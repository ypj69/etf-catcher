from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_failure_count_increments_once_per_run_and_quarantines_on_third_run() -> None:
    module = load_module(ROOT / "scripts" / "backfill_control.py", "backfill_control_test")
    state = {"schema_version": 1, "dates": {}}
    first = module.record_failure(state, "2026-08-20", "run-1", "failed", "t1")
    duplicate = module.record_failure(state, "2026-08-20", "run-1", "failed", "t1")
    second = module.record_failure(state, "2026-08-20", "run-2", "failed", "t2")
    third = module.record_failure(state, "2026-08-20", "run-3", "failed", "t3")
    assert first["failed_runs"] == 1
    assert duplicate["failed_runs"] == 1
    assert second["failed_runs"] == 2
    assert not second["quarantined"]
    assert third["failed_runs"] == 3
    assert third["quarantined"]


def test_success_removes_a_previously_failed_date() -> None:
    module = load_module(ROOT / "scripts" / "backfill_control.py", "backfill_control_success")
    state = {
        "schema_version": 1,
        "dates": {"2026-08-20": {"failed_runs": 2, "quarantined": False}},
    }
    result = module.record_success(state, "2026-08-20")
    assert result["previous_failures"] == 2
    assert state["dates"] == {}


def test_coverage_accepts_small_legal_blanks_but_rejects_large_gaps(tmp_path: Path) -> None:
    module = load_module(
        ROOT / "scripts" / "validate_daily_web_coverage.py", "coverage_test"
    )
    database = tmp_path / "coverage.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """CREATE TABLE etf_daily(
                trade_date TEXT,etf_code TEXT,close REAL,amount REAL,
                fund_share REAL,fund_scale REAL,net_flow REAL)"""
        )
        connection.executemany(
            "INSERT INTO etf_daily VALUES(?,?,?,?,?,?,?)",
            [
                (
                    "2026-08-20",
                    f"{index:06d}",
                    1.0,
                    1.0,
                    1.0,
                    1.0,
                    None if index < 5 else 1.0,
                )
                for index in range(100)
            ],
        )
        connection.executemany(
            "INSERT INTO etf_daily VALUES(?,?,?,?,?,?,?)",
            [
                (
                    "2026-08-21",
                    f"{index:06d}",
                    1.0,
                    1.0,
                    1.0,
                    1.0,
                    None if index < 6 else 1.0,
                )
                for index in range(100)
            ],
        )
    assert module.coverage_report(database, "2026-08-20")["status"] == "pass"
    failed = module.coverage_report(database, "2026-08-21")
    assert failed["status"] == "incomplete"
    assert "net_flow=94/100" in failed["reasons"]