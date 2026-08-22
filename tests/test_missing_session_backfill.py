from __future__ import annotations

import importlib.util
import json
import sqlite3
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def add_day(connection, trade_date: str, complete: bool = True) -> None:
    connection.executemany(
        "INSERT INTO etf_daily VALUES(?,?,?,?,?,?,?)",
        [
            (
                trade_date,
                f"{index:06d}",
                1.0,
                1.0 if complete else None,
                1.0 if complete else None,
                1.0 if complete else None,
                1.0 if complete else None,
            )
            for index in range(10)
        ],
    )


def fixture_state(tmp_path: Path, published: str):
    database = tmp_path / "etf_catcher.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """CREATE TABLE etf_daily(
                trade_date TEXT,etf_code TEXT,close REAL,amount REAL,
                fund_share REAL,fund_scale REAL,net_flow REAL)"""
        )
        add_day(connection, published)
    meta = tmp_path / "meta.json"
    meta.write_text(
        json.dumps({"market_latest": published, "flow_latest": published}),
        encoding="utf-8",
    )
    return database, meta


def test_downtime_plan_only_queues_sessions_after_publication(tmp_path: Path, monkeypatch) -> None:
    module = load_module(ROOT / "scripts" / "plan_missing_sessions.py", "plan_downtime")
    database, meta = fixture_state(tmp_path, "2026-08-19")
    observed = {}

    def sessions(start, end):
        observed.update(start=start, end=end)
        return (
            [date(2026, 8, 20), date(2026, 8, 21), date(2026, 8, 24), date(2026, 8, 25)],
            "test calendar",
        )

    monkeypatch.setattr(module, "actual_sessions", sessions)
    plan = module.build_plan(database, meta, date(2026, 8, 26))
    assert observed == {"start": date(2026, 8, 20), "end": date(2026, 8, 25)}
    assert plan["dates"] == ["2026-08-20", "2026-08-21", "2026-08-24", "2026-08-25"]
    assert plan["scope"] == "sessions strictly after the last successful web publication"


def test_ready_rows_inside_gap_are_not_collected_again(tmp_path: Path, monkeypatch) -> None:
    module = load_module(ROOT / "scripts" / "plan_missing_sessions.py", "plan_ready")
    database, meta = fixture_state(tmp_path, "2026-08-19")
    with sqlite3.connect(database) as connection:
        add_day(connection, "2026-08-20")
    monkeypatch.setattr(
        module,
        "actual_sessions",
        lambda start, end: ([date(2026, 8, 20), date(2026, 8, 21)], "test calendar"),
    )
    plan = module.build_plan(database, meta, date(2026, 8, 22))
    assert plan["gap_dates"] == ["2026-08-20", "2026-08-21"]
    assert plan["ready_dates"] == ["2026-08-20"]
    assert plan["dates"] == ["2026-08-21"]
    assert plan["publication_required"]


def test_partial_rows_inside_gap_remain_pending(tmp_path: Path, monkeypatch) -> None:
    module = load_module(ROOT / "scripts" / "plan_missing_sessions.py", "plan_partial")
    database, meta = fixture_state(tmp_path, "2026-08-20")
    with sqlite3.connect(database) as connection:
        add_day(connection, "2026-08-21", complete=False)
    monkeypatch.setattr(
        module,
        "actual_sessions",
        lambda start, end: ([date(2026, 8, 21)], "test calendar"),
    )
    plan = module.build_plan(database, meta, date(2026, 8, 22))
    assert plan["published_through"] == "2026-08-20"
    assert plan["dates"] == ["2026-08-21"]
    assert "amount=0/10" in plan["reasons"]["2026-08-21"]


def test_old_partial_history_before_watermark_is_not_requeued(tmp_path: Path, monkeypatch) -> None:
    module = load_module(ROOT / "scripts" / "plan_missing_sessions.py", "plan_old_history")
    database, meta = fixture_state(tmp_path, "2026-08-20")
    with sqlite3.connect(database) as connection:
        add_day(connection, "2026-08-18", complete=False)
    monkeypatch.setattr(
        module,
        "actual_sessions",
        lambda start, end: ([date(2026, 8, 21)], "test calendar"),
    )
    plan = module.build_plan(database, meta, date(2026, 8, 22))
    assert plan["gap_dates"] == ["2026-08-21"]
    assert "2026-08-18" not in plan["dates"]


def test_no_new_exchange_session_is_a_clean_noop(tmp_path: Path, monkeypatch) -> None:
    module = load_module(ROOT / "scripts" / "plan_missing_sessions.py", "plan_noop")
    database, meta = fixture_state(tmp_path, "2026-08-21")
    monkeypatch.setattr(module, "actual_sessions", lambda start, end: ([], "test calendar"))
    plan = module.build_plan(database, meta, date(2026, 8, 24))
    assert plan["dates"] == []
    assert not plan["publication_required"]
    assert plan["target_date"] == "2026-08-21"


def test_long_calendar_ranges_are_split_without_gaps() -> None:
    module = load_module(ROOT / "scripts" / "resolve_target_market_date.py", "calendar_chunks")
    chunks = list(module.calendar_chunks(date(2026, 1, 1), date(2026, 3, 10), days=31))
    assert chunks[0][0] == date(2026, 1, 1)
    assert chunks[-1][1] == date(2026, 3, 10)
    assert all((end - start).days <= 30 for start, end in chunks)
    assert all(chunks[index][1].toordinal() + 1 == chunks[index + 1][0].toordinal() for index in range(len(chunks) - 1))


def test_public_orchestrator_collects_then_publishes_once() -> None:
    text = (ROOT / "scripts" / "update_public.ps1").read_text(encoding="utf-8")
    loop = text.index("for($Index=0;$Index-lt$Dates.Count;$Index++)")
    collect = text.index("-CollectOnly", loop)
    publish = text.index("publish_web.ps1", collect)
    assert publish > collect
    assert "backfill_control.py" in text
    assert "Source gap" in text