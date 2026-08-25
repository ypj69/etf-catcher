from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from scripts.etf_classification import classify_etf
from scripts.maintain_etf_universe import (
    SourceEtf,
    due_for_run,
    ensure_local_universe,
    plan_changes,
    sync_database,
    validate_snapshot,
)


def row(code: str, name: str, enabled: str = "1", review_status: str = "auto_approved") -> dict[str, str]:
    return {
        "etf_code": code, "exchange": "SH" if code.startswith("5") else "SZ", "etf_name": name,
        "source_fund_type": "指数型-股票", "asset_class": "A股行业", "category_l1": "行业",
        "category_l2": "科技（半导体）", "classification_rule": "industry.semiconductor",
        "classification_confidence": "high" if review_status == "auto_approved" else "low",
        "review_status": review_status, "tracking_index_code": "", "tracking_index_name": "",
        "enabled": enabled, "history_start": "2025-01-01", "universe_source": "eastmoney_fundcode_search",
    }


def test_new_etf_is_enabled_only_when_classification_is_high_confidence():
    candidates = {
        "512001": SourceEtf("512001", "半导体ETF测试", "指数型-股票"),
        "512002": SourceEtf("512002", "神秘ETF测试", "指数型-股票"),
    }
    planned, _, events = plan_changes([], candidates, {}, date(2026, 8, 25), 3)
    by_code = {item["etf_code"]: item for item in planned}
    assert by_code["512001"]["enabled"] == "1"
    assert by_code["512002"]["enabled"] == "0"
    assert events["added_enabled"][0]["etf_code"] == "512001"
    assert events["added_review"][0]["etf_code"] == "512002"


def test_classifier_ignores_issuer_suffix_and_prioritizes_industry():
    assert classify_etf("创业板软件ETF国泰", "指数型-股票").classification_rule == "industry.computer_ai"
    assert classify_etf("工业有色ETF广发", "指数型-股票").classification_rule == "industry.metals"
    assert classify_etf("A500ETF中银证券", "指数型-股票").classification_rule == "broad.large"


def test_three_successful_weekly_absences_are_required_before_disable():
    rows, state = [row("512001", "半导体ETF测试")], {}
    for day in (date(2026, 8, 25), date(2026, 9, 1)):
        rows, state, events = plan_changes(rows, {}, state, day, 3)
        assert rows[0]["enabled"] == "1"
        assert not events["disabled"]
    rows, state, events = plan_changes(rows, {}, state, date(2026, 9, 8), 3)
    assert rows[0]["enabled"] == "0"
    assert events["disabled"][0]["misses"] == 3
    assert "512001" in state["maintenance_disabled"]


def test_maintenance_disabled_etf_reactivates_when_it_reappears():
    disabled = row("512001", "半导体ETF测试", "0", "inactive_confirmed")
    state = {"maintenance_disabled": {"512001": {"disabled_on": "2026-08-01"}}}
    candidates = {"512001": SourceEtf("512001", "半导体ETF测试", "指数型-股票")}
    rows, next_state, events = plan_changes([disabled], candidates, state, date(2026, 8, 25), 3)
    assert rows[0]["enabled"] == "1"
    assert "512001" not in next_state["maintenance_disabled"]
    assert events["reactivated"][0]["etf_code"] == "512001"


def test_due_gate_and_source_collapse_guard():
    assert not due_for_run({"last_success_date": "2026-08-25"}, date(2026, 8, 31), 7)
    assert due_for_run({"last_success_date": "2026-08-25"}, date(2026, 9, 1), 7)
    rows = [row(f"5{index:05d}", f"半导体ETF{index}") for index in range(1100)]
    candidates = {item["etf_code"]: SourceEtf(item["etf_code"], item["etf_name"], "指数型-股票") for item in rows[:800]}
    try:
        validate_snapshot(candidates, rows)
    except ValueError as exc:
        assert "guard" in str(exc)
    else:
        raise AssertionError("collapsed source must be rejected")


def test_local_universe_is_seeded_without_mutating_bundled_baseline(tmp_path: Path):
    baseline, local = tmp_path / "config.csv", tmp_path / "data" / "etf_universe.csv"
    baseline.write_text("etf_code,enabled\n510300,1\n", encoding="utf-8")
    ensure_local_universe(local, baseline)
    assert local.read_bytes() == baseline.read_bytes()
    local.write_text("local-change", encoding="utf-8")
    ensure_local_universe(local, baseline)
    assert local.read_text(encoding="utf-8") == "local-change"


def test_database_sync_disables_master_without_deleting_history(tmp_path: Path):
    database = tmp_path / "test.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript("""
            CREATE TABLE etf_master(etf_code TEXT PRIMARY KEY,exchange TEXT,etf_name TEXT,asset_class TEXT,category_l1 TEXT,category_l2 TEXT,source_fund_type TEXT,classification_rule TEXT,classification_confidence TEXT,review_status TEXT,tracking_index_code TEXT,tracking_index_name TEXT,active_from TEXT,active_to TEXT,enabled INTEGER,source TEXT,schema_version TEXT,updated_at TEXT);
            CREATE TABLE historical_values(etf_code TEXT,trade_date TEXT,value REAL);
            INSERT INTO historical_values VALUES('512001','2026-08-22',1.0);
        """)
        sync_database(connection, [row("512001", "半导体ETF测试", "0", "inactive_confirmed")], date(2026, 8, 25), {"512001": "2026-08-25"})
        master = connection.execute("SELECT enabled,active_to FROM etf_master WHERE etf_code='512001'").fetchone()
        history_count = connection.execute("SELECT COUNT(*) FROM historical_values").fetchone()[0]
    assert master == (0, "2026-08-25")
    assert history_count == 1


def test_daily_entry_invokes_weekly_maintenance_before_gap_plan():
    text = (Path(__file__).resolve().parents[1] / "scripts" / "update_public.ps1").read_text(encoding="utf-8-sig")
    assert text.index("maintain_etf_universe.py") < text.index("plan_missing_sessions.py")
