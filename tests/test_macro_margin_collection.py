import json
import importlib.util
import urllib.parse
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "build_macro_monitor_data", ROOT / "scripts" / "build_macro_monitor_data.py"
)
assert SPEC is not None and SPEC.loader is not None
macro = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(macro)


def _sse_rows(days):
    return [
        {"opDate": day.replace("-", ""), "rzye": value}
        for day, value in days.items()
    ]


def _history_rows(days):
    return [
        {"DIM_DATE": day, "RZYE": value}
        for day, value in days.items()
    ]


def test_backfills_every_complete_historical_gap_and_keeps_unpublished_day_missing(monkeypatch):
    sse = {
        "2026-08-17": 1_300_000_000_000,
        "2026-08-18": 1_310_000_000_000,
        "2026-08-19": 1_320_000_000_000,
        "2026-08-20": 1_330_000_000_000,
        "2026-08-21": 1_340_000_000_000,
    }
    szse_history = {
        "2026-08-18": 1_210_000_000_000,
        "2026-08-19": 1_220_000_000_000,
        "2026-08-20": 1_230_000_000_000,
    }

    def fake_fetch(url, referer=None, timeout=30):
        decoded = urllib.parse.unquote(url)
        if "commonSoaQuery" in url:
            return json.dumps({"result": _sse_rows(sse)})
        if "datacenter-web.eastmoney.com" in url:
            rows = sse if "SCDM=007" in decoded else szse_history
            return json.dumps({"result": {"data": _history_rows(rows)}})
        if "www.szse.cn" in url:
            return json.dumps([{"data": []}])
        raise AssertionError(url)

    monkeypatch.setattr(macro, "fetch_text", fake_fetch)
    monkeypatch.setattr(macro.time, "sleep", lambda _seconds: None)

    points, failures = macro.exchange_margin_daily(
        "2026-08-21", [("2026-08-17", 25_000.0)]
    )

    assert [day for day, _value in points] == [
        "2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20"
    ]
    assert dict(points)["2026-08-20"] == pytest.approx(25_600.0)
    assert failures == [
        "2026-08-21: SZSE financing balance not published for 2026-08-21"
    ]


def test_one_day_gap_uses_complete_market_history_without_redundant_szse_call(monkeypatch):
    szse_calls = []

    def fake_fetch(url, referer=None, timeout=30):
        decoded = urllib.parse.unquote(url)
        if "commonSoaQuery" in url:
            return json.dumps({"result": _sse_rows({"2026-08-21": 1_348_816_378_445})})
        if "datacenter-web.eastmoney.com" in url:
            value = 1_348_816_378_445 if "SCDM=007" in decoded else 1_275_000_000_000
            return json.dumps({"result": {"data": _history_rows({"2026-08-21": value})}})
        if "www.szse.cn" in url:
            szse_calls.append(url)
            return json.dumps([{"data": []}])
        raise AssertionError(url)

    monkeypatch.setattr(macro, "fetch_text", fake_fetch)
    monkeypatch.setattr(macro.time, "sleep", lambda _seconds: None)

    points, failures = macro.exchange_margin_daily("2026-08-21", [])

    assert failures == []
    assert szse_calls == []
    assert dict(points)["2026-08-21"] == pytest.approx(26_238.16378445)
