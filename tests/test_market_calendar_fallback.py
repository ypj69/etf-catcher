from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_tencent_calendar_parser_uses_real_rows_only() -> None:
    module = load_module(
        ROOT / "scripts" / "resolve_target_market_date.py", "calendar_parser"
    )
    payload = {
        "data": {
            "sh000300": {
                "day": [
                    ["2026-08-20", "1", "4.0"],
                    ["2026-08-21", "1", "4.1"],
                    ["2026-08-22", "1", "0"],
                ]
            }
        }
    }
    assert module.parse_tencent_sessions(
        json.dumps(payload), date(2026, 8, 20), date(2026, 8, 22)
    ) == [date(2026, 8, 20), date(2026, 8, 21)]


def test_actual_sessions_prefers_tencent_and_falls_back_to_ifind(monkeypatch) -> None:
    module = load_module(
        ROOT / "scripts" / "resolve_target_market_date.py", "calendar_fallback"
    )
    monkeypatch.setattr(
        module, "tencent_sessions", lambda start, end: [date(2026, 8, 21)]
    )
    monkeypatch.setattr(
        module,
        "ifind_sessions",
        lambda start, end: pytest.fail("iFinD fallback should not run"),
    )
    sessions, source = module.actual_sessions(date(2026, 8, 21), date(2026, 8, 21))
    assert sessions == [date(2026, 8, 21)]
    assert source.startswith("Tencent")

    monkeypatch.setattr(
        module, "tencent_sessions", lambda start, end: (_ for _ in ()).throw(OSError("down"))
    )
    monkeypatch.setattr(
        module, "ifind_sessions", lambda start, end: [date(2026, 8, 21)]
    )
    sessions, source = module.actual_sessions(date(2026, 8, 21), date(2026, 8, 21))
    assert sessions == [date(2026, 8, 21)]
    assert source.startswith("iFinD")


def test_actual_sessions_fails_closed_when_both_sources_fail(monkeypatch) -> None:
    module = load_module(
        ROOT / "scripts" / "resolve_target_market_date.py", "calendar_closed"
    )
    monkeypatch.setattr(
        module, "tencent_sessions", lambda start, end: (_ for _ in ()).throw(OSError("down"))
    )
    monkeypatch.setattr(
        module, "ifind_sessions", lambda start, end: (_ for _ in ()).throw(RuntimeError("down"))
    )
    with pytest.raises(RuntimeError, match="No reliable A-share trading calendar source"):
        module.actual_sessions(date(2026, 8, 21), date(2026, 8, 21))