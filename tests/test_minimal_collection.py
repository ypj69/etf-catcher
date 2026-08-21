from __future__ import annotations

import importlib.util
import json
import pytest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def ownership_job(answer: str) -> dict:
    inner = {
        "answer": answer,
        "indicators_params": {
            "基金份额": {"交易日期": "20260820", "单位": "份"},
            "基金规模": {"交易日期": "20260820", "单位": "万元"},
            "净流入额": {"交易日期": "20260820", "单位": "元"},
        },
    }
    return {
        "status": "success", "start_date": "2026-08-20", "answer": answer,
        "result": {"data": {"result": {"content": [{"text": json.dumps({"data": json.dumps(inner, ensure_ascii=False)}, ensure_ascii=False)}]}}},
    }


def test_ownership_query_is_the_only_ifind_etf_pass(tmp_path: Path, monkeypatch) -> None:
    prepare = load_module(ROOT / "scripts" / "prepare_ifind_direct_flow_jobs.py", "prepare_ownership")
    output = tmp_path / "jobs.json"
    monkeypatch.setattr("sys.argv", ["prepare", "--date", "2026-08-20", "--output", str(output), "--limit", "5"])
    prepare.main()
    query = json.loads(output.read_text(encoding="utf-8"))[0]["query"]
    assert all(field in query for field in ("基金份额", "基金规模", "净流入额"))
    assert all(field not in query for field in ("开盘价", "最高价", "最低价", "收盘价", "成交量", "成交额"))


def test_ownership_parser_handles_compound_scale_units(tmp_path: Path) -> None:
    ingest = load_module(ROOT / "scripts" / "ingest_ifind_direct_flows.py", "ownership_ingest")
    answer = """|证券代码|证券简称|日期|基金份额|基金规模|净流入额|
|---|---|---|---|---|---|
|159530.SZ|机器人ETF|20260820|237.4339亿|173.3852万|-5.371246915154亿|
"""
    result = tmp_path / "ownership.jsonl"
    result.write_text(json.dumps(ownership_job(answer), ensure_ascii=False) + "\n", encoding="utf-8")
    records, statuses = ingest.extract_records(result, "2026-08-20")
    assert statuses == {"success": 1}
    assert records["159530"]["fund_share"] == 23_743_390_000.0
    assert records["159530"]["fund_scale"] == 17_338_520_000.0
    assert records["159530"]["direct_net_flow"] == pytest.approx(-537_124_691.5154)


def test_daily_orchestration_uses_one_ifind_etf_collection() -> None:
    path = ROOT / "scripts" / ("update_one_day.ps1" if (ROOT / "scripts" / "update_one_day.ps1").is_file() else "update_production.ps1")
    text = path.read_text(encoding="utf-8")
    assert text.count("collect_ifind_incremental.js") == 1
    assert "ingest_market_minimal.py" in text
    assert "jobs_ownership_" in text
    assert "prepare_ifind_jobs_t1.py" not in text
def test_minimal_market_ingest_updates_close_amount_and_return(tmp_path: Path) -> None:
    import sqlite3

    market = load_module(ROOT / "scripts" / "ingest_market_minimal.py", "minimal_market_ingest")
    database = tmp_path / "market.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute(
        """CREATE TABLE etf_daily(
            trade_date TEXT, etf_code TEXT, close REAL, amount REAL, pct_change REAL,
            market_source TEXT, source_field TEXT, available_at TEXT, data_status TEXT,
            reason_code TEXT, schema_version TEXT, updated_at TEXT,
            PRIMARY KEY(trade_date, etf_code))"""
    )
    connection.execute("INSERT INTO etf_daily(trade_date,etf_code,close) VALUES('2026-08-19','510300',4.0)")
    connection.commit()
    connection.close()
    market.ingest(database, "2026-08-20", {"510300": {"close": 4.4, "amount": 123456.0}})
    connection = sqlite3.connect(database)
    row = connection.execute("SELECT close,amount,pct_change,market_source FROM etf_daily WHERE trade_date='2026-08-20'").fetchone()
    connection.close()
    assert row[0] == 4.4
    assert row[1] == 123456.0
    assert row[2] == pytest.approx(10.0)
    assert row[3] == "eastmoney_kline"
