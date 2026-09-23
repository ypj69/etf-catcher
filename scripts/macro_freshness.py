from __future__ import annotations

from datetime import date, timedelta
from typing import Any


MONTHLY_GROUPS = {
    "deposits": ("household_deposit_change", "nbfi_deposit_change"),
    "credit_core": ("social_increment", "social_stock_yoy"),
    "money": ("m1_yoy", "m2_yoy"),
    "credit_structure": ("household_long_term_loan", "enterprise_long_term_loan"),
    "pmi": ("manufacturing_pmi", "pmi_new_orders", "non_manufacturing_pmi", "composite_pmi"),
}

DAILY_TARGET_GROUPS = {
    "domestic_turnover": ("shanghai", "shenzhen", "total"),
}

DAILY_PEER_GROUPS = {
    "us_treasury_curve": ("ust_2y", "ust_10y", "ust_20y", "ust_30y", "ust_10y_2y_spread"),
}

DOLLAR_KIND_DXY = "dxy_daily"
DOLLAR_KIND_FRED_H10 = "fred_h10_broad"


def _observed_fixed_holiday(year: int, month: int, day: int) -> date:
    holiday = date(year, month, day)
    if holiday.weekday() == 5:
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:
        return holiday + timedelta(days=1)
    return holiday


def _nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (occurrence - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        last = date(year, 12, 31)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _us_federal_holidays(year: int) -> set[date]:
    """Return observed U.S. federal holidays that can delay H.10 release."""
    return {
        _observed_fixed_holiday(year, 1, 1),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _last_weekday(year, 5, 0),
        _observed_fixed_holiday(year, 6, 19),
        _observed_fixed_holiday(year, 7, 4),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 10, 0, 2),
        _observed_fixed_holiday(year, 11, 11),
        _nth_weekday(year, 11, 3, 4),
        _observed_fixed_holiday(year, 12, 25),
    }


def h10_expected_as_of(target_date: str) -> str:
    """Latest H.10 observation expected by the next 09:00 Asia/Shanghai run.

    H.10 publishes the previous U.S. business week's daily observations on
    Monday at 16:15 U.S. Eastern time. A Monday federal holiday delays that
    release until Tuesday, which is after Tuesday's 09:00 Shanghai run.
    """
    target = date.fromisoformat(target_date)
    release_monday = target - timedelta(days=target.weekday())
    expected_friday = release_monday - timedelta(days=3)
    if target.weekday() == 0 and release_monday in _us_federal_holidays(release_monday.year):
        expected_friday -= timedelta(days=7)
    return expected_friday.isoformat()


def dollar_series_kind(item: dict[str, Any]) -> str:
    explicit = str(item.get("source_series") or "")
    if explicit:
        return explicit
    source = str(item.get("source") or "")
    label = str(item.get("label") or "")
    note = str(item.get("note") or "")
    if "Federal Reserve Bank of St. Louis" in source or "广义贸易加权" in label or "DTWEXBGS" in note:
        return DOLLAR_KIND_FRED_H10
    return DOLLAR_KIND_DXY


def _series(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item.get("id"): item
        for tab in (payload.get("tabs") or {}).values()
        for item in tab.get("series", [])
        if item.get("id")
    }


def _month(value: Any) -> str:
    return str(value or "")[:7]


def _previous_month(value: str) -> str:
    year, month = (int(part) for part in value[:7].split("-"))
    month -= 1
    if month == 0:
        year -= 1
        month = 12
    return f"{year:04d}-{month:02d}"


def _scheduled_month(group_id: str, target_date: str) -> str:
    """Conservative release-calendar floor for monthly indicators.

    PMI for month M is normally available around the final day of M. Credit,
    money and deposit aggregates for M are released later in M+1, so before
    day 15 the last unquestionably due observation is M-1.
    """
    previous = _previous_month(target_date)
    if group_id == "pmi":
        return previous
    if int(target_date[8:10]) >= 15:
        return previous
    return _previous_month(previous)


def evaluate_macro_freshness(payload: dict[str, Any], target_date: str) -> dict[str, Any]:
    """Validate displayed macro series against their own publication cadence.

    Monthly releases are compared with fresh peers from the same official release,
    not blindly with the target trading month. If every peer still reports the
    previous month, the next month is considered not yet published and is normal.
    """
    by_id = _series(payload)
    checks: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    awaiting: list[str] = []

    def record(series_id: str, expected: str | None, status: str, reason: str) -> None:
        item = by_id.get(series_id) or {}
        checks[series_id] = {
            "actual_as_of": item.get("as_of"),
            "expected_as_of": expected,
            "status": status,
            "reason": reason,
        }
        if status in {"missing", "stale", "source_unverified"}:
            failures.append(series_id)
        elif status == "awaiting_publication":
            awaiting.append(series_id)

    def peer_group(group_id: str, ids: tuple[str, ...], monthly: bool) -> None:
        observed = [
            by_id[series_id].get("as_of")
            for series_id in ids
            if series_id in by_id
            and by_id[series_id].get("as_of")
        ]
        expected = max((_month(value) if monthly else str(value) for value in observed), default=None)
        peer_expected = expected
        if monthly:
            scheduled = _scheduled_month(group_id, target_date)
            expected = max(expected or scheduled, scheduled)
        if expected is None:
            for series_id in ids:
                record(series_id, None, "source_unverified", f"{group_id}本次没有任何成功刷新的同批指标")
            return
        next_release_pending = monthly and expected < _previous_month(target_date)
        for series_id in ids:
            item = by_id.get(series_id) or {}
            actual = _month(item.get("as_of")) if monthly else str(item.get("as_of") or "")
            if not actual:
                record(series_id, expected, "missing", f"{group_id}缺少数据")
            elif actual < expected:
                reason = (f"同批指标已发布至{expected}，该序列仍停在{actual}" if peer_expected and peer_expected >= expected
                          else f"按保守发布时间窗应达到{expected}，该序列仍停在{actual}；需核验发布与采集状态")
                record(series_id, expected, "stale", reason)
            elif next_release_pending:
                record(series_id, expected, "awaiting_publication", f"同批指标最新均为{expected}，下一月份尚未发布")
            else:
                record(series_id, expected, "current", f"已达到{group_id}当前应有日期")

    for group_id, ids in MONTHLY_GROUPS.items():
        peer_group(group_id, ids, monthly=True)

    for group_id, ids in DAILY_TARGET_GROUPS.items():
        for series_id in ids:
            actual = str((by_id.get(series_id) or {}).get("as_of") or "")
            if not actual:
                record(series_id, target_date, "missing", f"{group_id}缺少数据")
            elif actual < target_date:
                record(series_id, target_date, "stale", f"应更新至上一完整交易日{target_date}")
            else:
                record(series_id, target_date, "current", "已更新至上一完整交易日")

    for group_id, ids in DAILY_PEER_GROUPS.items():
        peer_group(group_id, ids, monthly=False)

    margin = by_id.get("margin_financing_balance") or {}
    margin_actual = str(margin.get("as_of") or "")
    if not margin_actual:
        record("margin_financing_balance", target_date, "missing", "融资余额缺少数据")
    elif margin_actual >= target_date:
        record("margin_financing_balance", target_date, "current", "已更新至上一完整交易日")
    elif margin.get("availability_status") == "awaiting_publication":
        record("margin_financing_balance", target_date, "awaiting_publication", "交易所尚未发布目标日完整两市数据")
    else:
        record("margin_financing_balance", target_date, "stale", "目标日数据缺失且未确认属于尚未发布")

    dollar = by_id.get("dollar_index") or {}
    dollar_actual = str(dollar.get("as_of") or "")
    if not dollar_actual:
        record("dollar_index", target_date, "missing", "美元指数缺少数据")
    else:
        kind = dollar_series_kind(dollar)
        if kind == DOLLAR_KIND_FRED_H10:
            expected = h10_expected_as_of(target_date)
            if dollar_actual > target_date or dollar_actual < expected:
                record("dollar_index", expected, "stale", f"FRED H.10周度发布应至少包含{expected}观测")
            else:
                record("dollar_index", expected, "current", "符合美联储H.10上一完整工作周发布节奏")
        else:
            lag = (date.fromisoformat(target_date) - date.fromisoformat(dollar_actual)).days
            if lag < 0 or lag > 4:
                record("dollar_index", target_date, "stale", "DXY日频数据超过允许的跨市场休市滞后")
            else:
                record("dollar_index", target_date, "current", "DXY处于跨市场日频允许日期范围")

    fed = by_id.get("fed_target_upper") or {}
    fomc_dates = ("2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09")
    expected_fomc = max((day for day in fomc_dates if day <= target_date), default=None)
    decision_date = str(fed.get("decision_date") or "") or None
    if expected_fomc and (not decision_date or decision_date < expected_fomc):
        record("fed_target_upper", expected_fomc, "stale", f"最近一次FOMC决议日为{expected_fomc}，尚未取得该次决议值")
    elif fed.get("as_of") and fed.get("latest") is not None:
        record("fed_target_upper", expected_fomc, "current", "已按最近一次FOMC决议公布日更新")
    else:
        record("fed_target_upper", expected_fomc, "missing", "政策利率没有可用观察值")

    return {
        "status": "pass" if not failures else "fail",
        "target_date": target_date,
        "checks": checks,
        "failures": sorted(set(failures)),
        "awaiting_publication": sorted(set(awaiting)),
    }
