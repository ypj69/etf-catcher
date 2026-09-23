from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("macro", ROOT / "scripts" / "build_macro_monitor_data.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def series(series_id: str, date: str):
    return {"id": series_id, "points": [{"date": date, "value": 1.0}]}


def test_completed_months_do_not_schedule_monthly_ifind(monkeypatch) -> None:
    old = {"tabs": {"retail_flow": {"series": [series("shanghai", "2026-08-19"), series("shenzhen", "2026-08-19"), series("total", "2026-08-19"), series("household_deposit_change", "2026-07-31"), series("nbfi_deposit_change", "2026-07-31")]}, "credit_pmi": {"series": [
        series("social_increment", "2026-07-31"), series("social_stock_yoy", "2026-07-31"),
        series("household_long_term_loan", "2026-07-31"), series("enterprise_long_term_loan", "2026-07-31"),
        series("m1_yoy", "2026-07-31"), series("m2_yoy", "2026-07-31"), series("manufacturing_pmi", "2026-07-31"), series("non_manufacturing_pmi", "2026-07-31"), series("composite_pmi", "2026-07-31"), series("pmi_new_orders", "2026-07-31")
    ]}}}
    monkeypatch.setattr(MODULE.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("iFinD should not run")))
    result = MODULE.run_ifind("2026-08-19", old)
    assert result["requested_keys"] == []
