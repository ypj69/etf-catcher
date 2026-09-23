from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_macro_monitor_data import (  # noqa: E402
    choose_dollar_source,
    clip_series_after,
    complete_turnover_values,
    merge_dollar_history,
    merge_series_history,
    parse_fomc_target_upper,
    parse_tencent_turnover,
    reconcile_refresh_diagnostics,
)
from macro_freshness import DOLLAR_KIND_DXY, DOLLAR_KIND_FRED_H10, evaluate_macro_freshness, h10_expected_as_of  # noqa: E402
from validate_t1_synchronized import embedded_freshness_matches  # noqa: E402


def item(series_id: str, as_of: str | None, status: str = "success", **extra):
    return {
        "id": series_id,
        "as_of": as_of,
        "latest": 1.0 if as_of else None,
        "refresh_status": status,
        "points": [] if not as_of else [{"date": as_of, "value": 1.0}],
        **extra,
    }


def payload(overrides=None):
    values = {
        "household_deposit_change": item("household_deposit_change", "2026-07-31"),
        "nbfi_deposit_change": item("nbfi_deposit_change", "2026-07-31"),
        "margin_financing_balance": item("margin_financing_balance", "2026-09-03", availability_status="awaiting_publication"),
        "shanghai": item("shanghai", "2026-09-04"),
        "shenzhen": item("shenzhen", "2026-09-04"),
        "total": item("total", "2026-09-04"),
        "social_increment": item("social_increment", "2026-07-31"),
        "social_stock_yoy": item("social_stock_yoy", "2026-07-31"),
        "m1_yoy": item("m1_yoy", "2026-07-31"),
        "m2_yoy": item("m2_yoy", "2026-07-31"),
        "household_long_term_loan": item("household_long_term_loan", "2026-07-31"),
        "enterprise_long_term_loan": item("enterprise_long_term_loan", "2026-07-31"),
        "manufacturing_pmi": item("manufacturing_pmi", "2026-08-31"),
        "pmi_new_orders": item("pmi_new_orders", "2026-08-31"),
        "non_manufacturing_pmi": item("non_manufacturing_pmi", "2026-08-31"),
        "composite_pmi": item("composite_pmi", "2026-08-31"),
        "ust_2y": item("ust_2y", "2026-09-04"),
        "ust_10y": item("ust_10y", "2026-09-04"),
        "ust_20y": item("ust_20y", "2026-09-04"),
        "ust_30y": item("ust_30y", "2026-09-04"),
        "ust_10y_2y_spread": item("ust_10y_2y_spread", "2026-09-04"),
        "dollar_index": item("dollar_index", "2026-09-04"),
        "fed_target_upper": item("fed_target_upper", "2026-07-29", "stale", decision_date="2026-07-29"),
    }
    values.update(overrides or {})
    return {"tabs": {"all": {"series": list(values.values())}}}


def test_unpublished_monthly_release_is_normal():
    result = evaluate_macro_freshness(payload(), "2026-09-04")
    assert result["status"] == "pass"
    assert result["checks"]["social_increment"]["status"] == "awaiting_publication"
    assert result["checks"]["margin_financing_balance"]["status"] == "awaiting_publication"
    assert result["checks"]["fed_target_upper"]["status"] == "current"


def test_fomc_statement_parser_reads_fractional_target_range():
    raw = "<p>The Committee decided to raise the target range for the federal funds rate by 1/4 percentage point to 3-3/4 to 4 percent.</p>"
    assert parse_fomc_target_upper(raw) == 4.0


def test_fomc_meeting_requires_current_decision_value():
    result = evaluate_macro_freshness(payload(), "2026-09-16")
    assert result["status"] == "fail"
    assert result["checks"]["fed_target_upper"]["expected_as_of"] == "2026-09-16"


def test_current_fomc_decision_passes_event_freshness():
    result = evaluate_macro_freshness(
        payload({"fed_target_upper": item("fed_target_upper", "2026-09-16", decision_date="2026-09-16")}),
        "2026-09-16",
    )
    assert result["checks"]["fed_target_upper"]["status"] == "current"


def test_one_missing_series_after_peer_release_fails():
    result = evaluate_macro_freshness(
        payload({"non_manufacturing_pmi": item("non_manufacturing_pmi", "2026-07-31", "stale")}),
        "2026-09-04",
    )
    assert result["status"] == "fail"
    assert result["checks"]["non_manufacturing_pmi"]["expected_as_of"] == "2026-08"
    assert result["checks"]["non_manufacturing_pmi"]["status"] == "stale"


def test_daily_domestic_series_must_reach_target_trade_date():
    result = evaluate_macro_freshness(
        payload({"shenzhen": item("shenzhen", "2026-09-03", "stale")}),
        "2026-09-04",
    )
    assert result["status"] == "fail"
    assert result["checks"]["shenzhen"]["status"] == "stale"


def test_fred_h10_uses_previous_complete_business_week():
    result = evaluate_macro_freshness(
        payload({
            "shanghai": item("shanghai", "2026-09-09"),
            "shenzhen": item("shenzhen", "2026-09-09"),
            "total": item("total", "2026-09-09"),
            "dollar_index": item(
                "dollar_index",
                "2026-09-04",
                source="Federal Reserve Bank of St. Louis (FRED)",
                source_series=DOLLAR_KIND_FRED_H10,
            ),
        }),
        "2026-09-09",
    )
    assert result["status"] == "pass"
    assert result["checks"]["dollar_index"]["status"] == "current"
    assert result["checks"]["dollar_index"]["expected_as_of"] == "2026-09-04"


def test_fred_h10_fails_after_next_weekly_release_is_due():
    result = evaluate_macro_freshness(
        payload({
            "shanghai": item("shanghai", "2026-09-15"),
            "shenzhen": item("shenzhen", "2026-09-15"),
            "total": item("total", "2026-09-15"),
            "dollar_index": item(
                "dollar_index",
                "2026-09-04",
                source_series=DOLLAR_KIND_FRED_H10,
            ),
        }),
        "2026-09-15",
    )
    assert result["status"] == "fail"
    assert result["checks"]["dollar_index"]["expected_as_of"] == "2026-09-11"


def test_fred_h10_accounts_for_monday_federal_holiday_delay():
    assert h10_expected_as_of("2026-09-07") == "2026-08-28"


def test_non_fred_dollar_series_remains_stale_after_four_days():
    result = evaluate_macro_freshness(payload(), "2026-09-09")
    assert result["status"] == "fail"
    assert result["checks"]["dollar_index"]["status"] == "stale"


def test_stale_dxy_automatically_falls_back_to_h10():
    values, source_key, source_series, note = choose_dollar_source(
        [("2026-09-01", 100.0)],
        [("2026-09-04", 118.0)],
        "2026-09-10",
    )
    assert values[-1][0] == "2026-09-04"
    assert source_key == "fred_h10"
    assert source_series == DOLLAR_KIND_FRED_H10
    assert "不混接" in note


def test_dollar_source_switch_never_merges_incompatible_index_levels():
    kept = {
        "source_series": DOLLAR_KIND_FRED_H10,
        "points": [{"date": "2026-09-04", "value": 118.0}],
    }
    current = {
        "source_series": DOLLAR_KIND_DXY,
        "points": [{"date": "2026-09-10", "value": 97.0}],
        "latest": 97.0,
        "previous": None,
        "as_of": "2026-09-10",
    }
    selected = merge_dollar_history(kept, current)
    assert selected["points"] == current["points"]


def test_validation_rejects_stale_embedded_macro_assessment():
    macro = payload({
        "shanghai": item("shanghai", "2026-09-10"),
        "shenzhen": item("shenzhen", "2026-09-10"),
        "total": item("total", "2026-09-10"),
        "dollar_index": item(
            "dollar_index",
            "2026-09-04",
            source_series=DOLLAR_KIND_FRED_H10,
        ),
    })
    computed = evaluate_macro_freshness(macro, "2026-09-10")
    macro["freshness"] = {**computed, "status": "fail"}
    assert not embedded_freshness_matches(macro, computed)
    macro["freshness"] = computed
    assert embedded_freshness_matches(macro, computed)


def test_collection_error_becomes_warning_when_final_data_is_fresh():
    errors, warnings, status = reconcile_refresh_diagnostics(
        {"exchange_margin": "temporary TLS timeout"},
        {"eastmoney_turnover": "optional fallback unavailable"},
        {"status": "pass", "failures": []},
    )
    assert errors == {}
    assert warnings["collection_exchange_margin"] == "temporary TLS timeout"
    assert status == "success"


def test_collection_error_remains_failure_when_key_series_is_stale():
    errors, warnings, status = reconcile_refresh_diagnostics(
        {"dollar_fred_h10": "timeout"},
        {},
        {"status": "fail", "failures": ["dollar_index"]},
    )
    assert errors["dollar_fred_h10"] == "timeout"
    assert errors["stale_series"] == "dollar_index"
    assert warnings == {}
    assert status == "partial"


def test_turnover_missing_leg_is_derived_without_overwriting_direct_history():
    values, derived = complete_turnover_values({
        "shanghai": [("2026-09-03", 8206.03), ("2026-09-04", 8100.0)],
        "shenzhen": [("2026-09-03", 9400.0)],
        "total": [("2026-09-03", 17606.03), ("2026-09-04", 18000.0)],
    })
    assert dict(values["shenzhen"])["2026-09-03"] == 9400.0
    assert dict(values["shenzhen"])["2026-09-04"] == 9900.0
    assert derived["shenzhen"] == ["2026-09-04"]


def test_tencent_turnover_uses_requested_day_final_cumulative_amount():
    payload = {"data": {"sz399001": {"data": [
        {"date": "20260907", "data": ["1127 13698.21 1 656549052382"]},
        {"date": "20260904", "data": ["0930 1 1 100", "1500 13516.97 678475372 1092412649251.37"]},
    ]}}}
    assert parse_tencent_turnover(payload, "sz399001", "2026-09-04") == 10924.1264925137


def test_monthly_release_schedule_does_not_require_unpublished_credit_data():
    stale_flags = {
        key: item(key, "2026-07-31", "stale")
        for key in ("social_increment", "social_stock_yoy", "m1_yoy", "m2_yoy")
    }
    result = evaluate_macro_freshness(payload(stale_flags), "2026-09-04")
    assert result["status"] == "pass"
    assert result["checks"]["social_increment"]["status"] == "awaiting_publication"


def test_retained_macro_series_is_clipped_to_publication_target():
    original = {"tabs": {"retail_flow": {"series": [{
        "id": "total",
        "points": [
            {"date": "2026-09-03", "value": 10.0, "previous": None},
            {"date": "2026-09-04", "value": 11.0, "previous": 10.0},
        ],
        "latest": 11.0,
        "previous": 10.0,
        "as_of": "2026-09-04",
    }]}}}
    clipped = clip_series_after(original, "2026-09-03")
    series = clipped["tabs"]["retail_flow"]["series"][0]
    assert series["as_of"] == "2026-09-03"
    assert series["latest"] == 10.0
    assert len(series["points"]) == 1


def test_incremental_refresh_merges_history_instead_of_replacing_chart():
    kept = {"points": [
        {"date": "2026-01-05", "value": 10.0},
        {"date": "2026-09-02", "value": 20.0},
    ]}
    current = {"id": "shanghai", "points": [{"date": "2026-09-03", "value": 21.0}]}
    merged = merge_series_history(kept, current)
    assert [point["date"] for point in merged["points"]] == ["2026-01-05", "2026-09-02", "2026-09-03"]
    assert merged["latest"] == 21.0
