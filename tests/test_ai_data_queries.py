from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from ai_data_queries import date_range, encode_context, flow_ranking, flow_summary, query_dates, ranking_request


@pytest.fixture
def conn():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("CREATE TABLE etf_master(etf_code TEXT,etf_name TEXT,enabled INTEGER); CREATE TABLE etf_daily(trade_date TEXT,etf_code TEXT,net_flow REAL);")
    db.executemany("INSERT INTO etf_master VALUES(?,?,?)", [("A", "完整流入", 1), ("B", "缺失产品", 1), ("C", "完整流出", 1), ("D", "已停用", 0)])
    db.executemany("INSERT INTO etf_daily VALUES(?,?,?)", [("2026-07-14", "A", 10), ("2026-07-15", "A", 20), ("2026-07-14", "B", 999), ("2026-07-15", "B", None), ("2026-07-14", "C", -5), ("2026-07-15", "C", -6), ("2026-07-14", "D", 1000), ("2026-07-15", "D", 1000), ("2026-07-16", "A", 5000)])
    yield db
    db.close()


def test_date_parsing():
    assert date_range("7月14日到8月13日", "2026-09-15") == ("2026-07-14", "2026-08-13")
    assert date_range("2025-07-14至2025/08/13", "2026-09-15") == ("2025-07-14", "2025-08-13")
    assert date_range("2025年12月30日到1月5日", "2026-09-15") == ("2025-12-30", "2026-01-05")
    with pytest.raises(ValueError):
        date_range("2026年2月30日", "2026-09-15")


def test_rank_and_null_policy(conn):
    r = flow_ranking(conn, "2026-07-14", "2026-07-15", 2, 10, False)
    assert [x["etf_code"] for x in r["rows"]] == ["A"]
    assert r["rows"][0]["net_flow"] == 30
    assert r["excluded_incomplete_etfs"] == 1
    assert flow_ranking(conn, "2026-07-14", "2026-07-15", 2, 10, True)["rows"][0]["net_flow"] == -11
    assert flow_summary(conn, "B", "2026-07-14", "2026-07-15", 2)["complete"] is False
    assert flow_summary(conn, "B", "2026-07-15", "2026-07-15", 1)["net_flow"] is None


def test_publication_and_relative_windows(conn):
    a, b, c = query_dates(conn, "最近一天净流入前十ETF", 60, "2026-07-15")
    assert (a, b, c["trading_days"]) == ("2026-07-15", "2026-07-15", 1)
    assert query_dates(conn, "近20个交易日ETF净流出前五", 20, "2026-07-15")[2]["trading_days"] == 2
    assert ranking_request("最近一天净流入前十ETF") == (10, False)
    assert ranking_request("ETF净流出前二十") == (20, True)
    assert ranking_request("成交额前十ETF") is None


def test_budget_preserves_totals_and_ranks():
    sections = [{"type": "ETF历史", "summary": {"net_flow": 123}, "rows": [{"trade_date": str(i), "text": "x" * 100} for i in range(200)]}, {"type": "ETF净流入排名", "rows": [{"net_flow": 99}]}]
    coverage = {}
    encoded = encode_context(sections, coverage, limit=5000)
    assert len(encoded) <= 5000
    data = json.loads(encoded)
    assert data[0]["summary"]["net_flow"] == 123
    assert data[1]["rows"] == [{"net_flow": 99}]
    assert coverage["omitted_series"]
