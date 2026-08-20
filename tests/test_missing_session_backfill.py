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


def fixture_state(tmp_path: Path, market: str, flow: str, meta_market: str, meta_flow: str):
    database = tmp_path / "etf_catcher.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE etf_daily(trade_date TEXT,close REAL,net_flow REAL)")
        connection.execute("INSERT INTO etf_daily VALUES(?,?,NULL)", (market, 1.0))
        connection.execute("INSERT INTO etf_daily VALUES(?,NULL,?)", (flow, 1.0))
    meta = tmp_path / "meta.json"
    meta.write_text(
        json.dumps({"market_latest": meta_market, "flow_latest": meta_flow}),
        encoding="utf-8",
    )
    return database, meta


def test_first_install_plans_every_actual_session_in_order(tmp_path: Path, monkeypatch) -> None:
    module = load_module(ROOT / "scripts" / "plan_missing_sessions.py", "plan_first_install")
    database, meta = fixture_state(tmp_path, "2026-08-19", "2026-08-19", "2026-08-19", "2026-08-19")
    observed = {}

    def sessions(start, end):
        observed.update(start=start, end=end)
        return [date(2026, 8, 20), date(2026, 8, 21), date(2026, 8, 24), date(2026, 8, 25)]

    monkeypatch.setattr(module, "ifind_sessions", sessions)
    plan = module.build_plan(database, meta, date(2026, 8, 26))
    assert observed == {"start": date(2026, 8, 20), "end": date(2026, 8, 25)}
    assert plan["dates"] == ["2026-08-20", "2026-08-21", "2026-08-24", "2026-08-25"]
    assert plan["missing_count"] == 4
    assert plan["target_date"] == "2026-08-25"


def test_partial_future_rows_do_not_advance_published_watermark(tmp_path: Path, monkeypatch) -> None:
    module = load_module(ROOT / "scripts" / "plan_missing_sessions.py", "plan_partial_rows")
    database, meta = fixture_state(tmp_path, "2026-08-21", "2026-08-20", "2026-08-20", "2026-08-20")
    monkeypatch.setattr(
        module,
        "ifind_sessions",
        lambda start, end: [date(2026, 8, 21), date(2026, 8, 24), date(2026, 8, 25)],
    )
    plan = module.build_plan(database, meta, date(2026, 8, 26))
    assert plan["published_through"] == "2026-08-20"
    assert plan["dates"][0] == "2026-08-21"


def test_no_new_exchange_session_is_a_clean_noop(tmp_path: Path, monkeypatch) -> None:
    module = load_module(ROOT / "scripts" / "plan_missing_sessions.py", "plan_noop")
    database, meta = fixture_state(tmp_path, "2026-08-21", "2026-08-21", "2026-08-21", "2026-08-21")
    monkeypatch.setattr(module, "ifind_sessions", lambda start, end: [])
    plan = module.build_plan(database, meta, date(2026, 8, 24))
    assert plan["dates"] == []
    assert plan["target_date"] == "2026-08-21"


def test_long_calendar_ranges_are_split_without_gaps() -> None:
    module = load_module(ROOT / "scripts" / "resolve_target_market_date.py", "calendar_chunks")
    chunks = list(module.calendar_chunks(date(2026, 1, 1), date(2026, 3, 10)))
    assert chunks[0][0] == date(2026, 1, 1)
    assert chunks[-1][1] == date(2026, 3, 10)
    assert all((end - start).days <= 30 for start, end in chunks)
    assert all(chunks[index][1].toordinal() + 1 == chunks[index + 1][0].toordinal() for index in range(len(chunks) - 1))


def test_public_orchestrator_runs_planned_dates_chronologically() -> None:
    text = (ROOT / "scripts" / "update_public.ps1").read_text(encoding="utf-8")
    assert "plan_missing_sessions.py" in text
    assert "for($Index=0;$Index-lt$Dates.Count;$Index++)" in text
    assert "update_one_day.ps1" in text
    assert "all missing trading sessions published in chronological order" in text
