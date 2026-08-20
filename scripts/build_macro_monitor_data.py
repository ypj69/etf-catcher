from __future__ import annotations

import argparse
import calendar
import csv
import io
import json
import math
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "web" / "macro_monitor.json"
START = "2026-01-01"
IFIND = ROOT / "backend" / "ifind_macro_data.js"

SOURCES = {
    "pbc": ("中国人民银行", "https://www.pbc.gov.cn/diaochatongjisi/116219/index.html"),
    "nbs": ("国家统计局", "https://data.stats.gov.cn/"),
    "ifind": ("同花顺 iFinD", "https://www.51ifind.com/"),
    "treasury": ("美国财政部 Daily Treasury Par Yield Curve Rates", "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView"),
    "fred": ("Federal Reserve Bank of St. Louis (FRED)", "https://fred.stlouisfed.org/"),
    "fed": ("Federal Reserve FOMC calendar", "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"),
    "exchanges": ("上海证券交易所、深圳证券交易所", "https://www.sse.com.cn/market/othersdata/margin/detail/index.shtml"),
    "margin_sources": ("上海证券交易所、深圳证券交易所；东方财富Choice历史汇总", "https://data.eastmoney.com/rzrq/detail/all.html"),
}

DEPOSIT_YTD = [
    ("2026-01-31", 2.13, 1.45), ("2026-02-28", 5.24, 2.84),
    ("2026-03-31", 7.68, 2.03), ("2026-04-30", 5.74, 4.50),
    ("2026-05-31", 5.63, 5.64), ("2026-06-30", 7.58, 4.65),
    ("2026-07-31", 6.95, 5.76),
]

PMI_SEED = {
    "manufacturing_pmi": [49.3, 49.0, 50.4, 50.3, 50.0, 50.3, 49.2],
    "non_manufacturing_pmi": [49.4, 49.5, 50.1, 49.4, 50.1, 50.2, 49.0],
    "composite_pmi": [49.8, 49.5, 50.5, 50.1, 50.5, 50.6, 49.3],
    "pmi_new_orders": [49.2, 48.6, 51.6, 50.6, 49.9, 51.2, 48.5],
}
MONEY_SEED = {"m1_yoy": [4.9, 5.9, 5.1, 5.0, 5.5, 4.0, 4.0], "m2_yoy": [9.0, 9.0, 8.5, 8.6, 8.6, 8.0, 7.7]}
CREDIT_STRUCTURE_SEED = {
    "household_long_term_loan": [0.3469, -0.1815, 0.2953, -0.3408, -0.0571, 0.1584, -0.1202],
    "enterprise_long_term_loan": [3.18, 0.89, 1.35, -0.41, -0.02, 0.56, -0.23],
}
FOMC_2026 = [
    ("2026-01-28", "1月会议"), ("2026-03-18", "3月会议·经济预测"),
    ("2026-04-29", "4月会议"), ("2026-06-17", "6月会议·经济预测"),
    ("2026-07-29", "7月会议"), ("2026-09-16", "9月会议·经济预测"),
    ("2026-10-28", "10月会议"), ("2026-12-09", "12月会议·经济预测"),
]


def load(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def number(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    text = str(value).replace(",", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group()) if match else None


def normalize_date(value, monthly=False):
    text = str(value or "").strip().replace("/", "-").replace("年", "-").replace("月", "").replace("日", "")
    for pattern in ("%m-%d-%Y", "%Y-%m-%d", "%Y-%m"):
        try:
            parsed = datetime.strptime(text, pattern)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            pass
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    if len(digits) >= 6:
        return f"{digits[:4]}-{digits[4:6]}-01" if monthly else f"{digits[:4]}-{digits[4:6]}-01"
    return None


def source(key):
    return {"title": SOURCES[key][0], "url": SOURCES[key][1]}


def make_series(series_id, label, unit, points, source_key, status="success", note=""):
    clean = []
    for item in sorted(points, key=lambda row: row[0]):
        if item[0] >= START and item[1] is not None:
            clean.append({"date": item[0], "value": round(float(item[1]), 6)})
    for index, point in enumerate(clean):
        point["previous"] = clean[index - 1]["value"] if index else None
    src = source(source_key)
    return {"id": series_id, "label": label, "unit": unit, "latest": clean[-1]["value"] if clean else None,
            "previous": clean[-2]["value"] if len(clean) > 1 else None, "as_of": clean[-1]["date"] if clean else None,
            "source": src["title"], "source_url": src["url"], "refresh_status": status, "note": note, "points": clean}


def month_key(value):
    return str(value or "")[:7]


def month_shift(month, offset):
    year, current = (int(part) for part in month.split("-"))
    absolute = year * 12 + current - 1 + offset
    return f"{absolute // 12:04d}-{absolute % 12 + 1:02d}"


def month_end_date(month):
    year, current = (int(part) for part in month.split("-"))
    return f"{month}-{calendar.monthrange(year, current)[1]:02d}"


def series_month_values(series):
    return {month_key(point.get("date")): number(point.get("value")) for point in series.get("points", [])}


def credit_score(delta):
    if delta >= 0.30:
        return 2
    if delta > 0.10:
        return 1
    if delta >= -0.10:
        return 0
    if delta > -0.30:
        return -1
    return -2


def pmi_score(current, previous, previous_two):
    latest_change = current - previous
    earlier_change = previous - previous_two
    if latest_change > 0 and earlier_change > 0:
        return 2 if current > 50 else 1
    if latest_change < 0 and earlier_change < 0:
        return -1 if current >= 50 else -2
    return 0


def regime_label(total):
    if total >= 3:
        return "上行确认"
    if total >= 1:
        return "改善观察"
    if total == 0:
        return "方向混沌"
    if total >= -2:
        return "转弱观察"
    return "下行确认"


def trend_word(value, positive="改善", negative="走弱"):
    if value > 0:
        return positive
    if value < 0:
        return negative
    return "持平"


def structure_share_value(household, enterprise, social_increment):
    if social_increment is None or social_increment <= 0.1:
        return None
    return (household + enterprise) / social_increment * 100


def build_compass(series_by_id):
    stock = series_by_id.get("social_stock_yoy") or {}
    manufacturing = series_by_id.get("manufacturing_pmi") or {}
    stock_values = series_month_values(stock)
    pmi_values = series_month_values(manufacturing)
    common = sorted(set(stock_values) & set(pmi_values), reverse=True)
    effective = next((month for month in common if month_shift(month, -3) in stock_values and month_shift(month, -1) in pmi_values and month_shift(month, -2) in pmi_values), None)
    base = {"method_version": "dual_leading_compass_v1", "available": False, "effective_month": effective,
            "refresh_status": "missing", "score_credit": None, "score_pmi": None, "score_total": None,
            "regime": "数据不足", "divergence": False, "summary": "关键数据不足，暂不形成新的综合判断。"}
    if not effective:
        return base
    stock_delta = round(stock_values[effective] - stock_values[month_shift(effective, -3)], 6)
    latest_pmi = pmi_values[effective]
    previous_pmi = pmi_values[month_shift(effective, -1)]
    previous_two_pmi = pmi_values[month_shift(effective, -2)]
    s_score = credit_score(stock_delta)
    p_score = pmi_score(latest_pmi, previous_pmi, previous_two_pmi)
    total = s_score + p_score
    divergence = s_score * p_score < 0 and abs(s_score) >= 1 and abs(p_score) >= 1
    stale = stock.get("refresh_status") != "success" or manufacturing.get("refresh_status") != "success"
    new_orders = series_month_values(series_by_id.get("pmi_new_orders") or {})
    household = series_month_values(series_by_id.get("household_long_term_loan") or {})
    enterprise = series_month_values(series_by_id.get("enterprise_long_term_loan") or {})
    structure_parts = []
    if effective in household:
        structure_parts.append(f"居民中长期贷款当月{trend_word(household[effective], '增加', '减少')}")
    if effective in enterprise:
        structure_parts.append(f"企业中长期贷款当月{trend_word(enterprise[effective], '增加', '减少')}")
    if effective in new_orders and month_shift(effective, -1) in new_orders:
        change = new_orders[effective] - new_orders[month_shift(effective, -1)]
        structure_parts.append(f"PMI新订单{trend_word(change)}至{new_orders[effective]:.1f}")
    direction = "回升" if stock_delta > 0.10 else "回落" if stock_delta < -0.10 else "基本持平"
    pmi_direction = "连续回升" if p_score > 0 else "连续回落" if p_score < 0 else "尚未形成连续方向"
    prefix = "关键序列本次刷新未完成，以下沿用最近有效观察。" if stale else ""
    effective_year, effective_month = effective.split("-")
    signed = lambda value: f"{value:+d}" if value else "0"
    summary = (f"{prefix}{effective_year}年{int(effective_month)}月，社融存量同比较3个月前{direction}{abs(stock_delta):.1f}个百分点，"
               f"信用方向S={signed(s_score)}；制造业PMI为{latest_pmi:.1f}，{pmi_direction}，景气拐点P={signed(p_score)}。"
               f"双领先罗盘合计{signed(total)}分，处于“{regime_label(total)}”阶段；"
               f"{'信用与景气方向背离。' if divergence else '信用与景气未触发方向背离。'}")
    if structure_parts:
        summary += "结构证据显示：" + "，".join(structure_parts) + "。"
    summary += "该判断仅用于宏观研究监控，不构成投资建议。"
    return {**base, "available": True, "refresh_status": "stale" if stale else "success",
            "score_credit": s_score, "score_pmi": p_score, "score_total": total,
            "regime": regime_label(total), "divergence": divergence,
            "social_stock_delta_3m": stock_delta, "manufacturing_pmi": latest_pmi,
            "summary": summary}


def latest_series_date(old, tab, series_id):
    points = old_series_points(old, tab, series_id)
    return max((day for day, value in points if day and value is not None), default=None)


def run_ifind(end, old):
    end_date = datetime.strptime(end, "%Y-%m-%d")
    previous_month = month_shift(end[:7], -1)
    pmi_month = end[:7] if end_date.day == calendar.monthrange(end_date.year, end_date.month)[1] else previous_month
    definitions = {
        "credit_increment": ("social_increment", previous_month),
        "credit_stock": ("social_stock_yoy", previous_month),
        "household_long_term": ("household_long_term_loan", previous_month),
        "enterprise_long_term": ("enterprise_long_term_loan", previous_month),
        "money": ("m2_yoy", previous_month),
        "pmi": ("manufacturing_pmi", pmi_month),
        "pmi_new_orders": ("pmi_new_orders", pmi_month),
        "deposits": ("household_deposit_change", previous_month),
    }
    keys, starts, target_months = [], {}, {}
    if latest_series_date(old, "retail_flow", "total") != end:
        keys.append("turnover"); starts["turnover"] = end
    for key, (series_id, target_month) in definitions.items():
        latest = latest_series_date(old, "credit_pmi" if key != "deposits" else "retail_flow", series_id)
        if not latest or month_key(latest) < target_month:
            keys.append(key)
            starts[key] = "2026-01" if key == "deposits" or not latest else month_shift(month_key(latest), 1)
            target_months[key] = target_month
    if not keys:
        return {"status": "pass", "requested_keys": [], "results": {}, "errors": {}}
    command = ["node", str(IFIND)]
    payload = json.dumps({"end": end, "keys": keys, "starts": starts, "target_months": target_months}, ensure_ascii=False)
    result = subprocess.run(command, input=payload, capture_output=True, text=True, encoding="utf-8", timeout=180, check=True)
    return json.loads(result.stdout)


def rows(ifind, key):
    return [row for table in ifind.get("results", {}).get(key, []) for row in table.get("rows", []) if isinstance(row, dict)]


def date_column(row):
    return next((key for key in row if any(token in str(key) for token in ("日期", "时间", "指标时间"))), None)


def find_values(ifind, key, definitions, monthly=False, scale=1.0):
    found = {series_id: [] for series_id in definitions}
    for row in rows(ifind, key):
        dkey = date_column(row)
        day = normalize_date(row.get(dkey), monthly) if dkey else None
        if not day:
            continue
        for series_id, patterns in definitions.items():
            for column, value in row.items():
                if column == dkey or not all(token in str(column) for token in patterns):
                    continue
                parsed = number(value)
                if parsed is not None:
                    found[series_id].append((day, parsed * scale))
                    break
    return found


def fetch_csv(url):
    request = urllib.request.Request(url, headers={"User-Agent": "ETF-Catcher-Macro-Monitor/1.0"})
    with urllib.request.urlopen(request, timeout=35) as response:
        return response.read().decode("utf-8-sig")


def fetch_text(url, referer=None):
    headers = {"User-Agent": "ETF-Catcher-Macro-Monitor/1.0"}
    if referer:
        headers["Referer"] = referer
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=35) as response:
        return response.read().decode("utf-8-sig")


def old_series_points(old, tab, series_id):
    for item in (old or {}).get("tabs", {}).get(tab, {}).get("series", []):
        if item.get("id") == series_id:
            return [(point.get("date"), number(point.get("value"))) for point in item.get("points", [])]
    return []


def exchange_margin_daily(end, existing_points=None):
    """Return daily SSE+SZSE financing balances, incrementally filling missing trading days."""
    params = urllib.parse.urlencode({
        "isPagination": "true",
        "pageHelp.pageSize": 400,
        "beginDate": START.replace("-", ""),
        "endDate": end.replace("-", ""),
        "sqlId": "RZRQ_HZ_INFO",
    })
    sse_url = f"https://query.sse.com.cn/commonSoaQuery.do?{params}"
    sse_payload = json.loads(fetch_text(sse_url, "https://www.sse.com.cn/"))
    sse_rows = sse_payload.get("result") or sse_payload.get("pageHelp", {}).get("data") or []
    sse_daily = {}
    for row in sse_rows:
        raw_day = str(row.get("opDate") or "")
        value = number(row.get("rzye"))
        if len(raw_day) != 8 or value is None:
            continue
        day = normalize_date(raw_day)
        if START <= day <= end:
            sse_daily[day] = value / 1e8

    existing = {
        day: value for day, value in (existing_points or [])
        if day in sse_daily and value is not None and day <= end
    }
    missing_days = [day for day in sorted(sse_daily) if day not in existing]

    # On the one-time history migration, avoid hundreds of SZSE day-by-day calls.
    # Eastmoney's public chart exposes separate market aggregates: 007=SSE,
    # 001=SZSE and 002=BSE. Only 007+001 are merged here; BSE is never requested.
    if len(missing_days) > 5:
        market_history = {}
        for market_code in ("007", "001"):
            history_params = urllib.parse.urlencode({
                "reportName": "RPTA_WEB_RZRQ_LSSH", "columns": "ALL", "source": "WEB",
                "sortColumns": "DIM_DATE", "sortTypes": "-1", "pageNumber": 1,
                "pageSize": 500, "filter": f"(SCDM={market_code})",
            })
            history_url = f"https://datacenter-web.eastmoney.com/api/data/v1/get?{history_params}"
            payload = json.loads(fetch_text(history_url, "https://data.eastmoney.com/rzrq/detail/all.html"))
            for row in (payload.get("result") or {}).get("data", []):
                day = normalize_date(row.get("DIM_DATE"))
                value = number(row.get("RZYE"))
                if day in sse_daily and day <= end and value is not None:
                    market_history.setdefault(day, {})[market_code] = value / 1e8
        for day, values in market_history.items():
            if set(values) == {"007", "001"}:
                existing[day] = values["007"] + values["001"]
        missing_days = [day for day in sorted(sse_daily) if day not in existing]

    def fetch_szse(day):
        szse_params = urllib.parse.urlencode({
            "SHOWTYPE": "JSON", "CATALOGID": "1837_xxpl", "TABKEY": "tab1", "txtDate": day,
        })
        szse_url = f"https://www.szse.cn/api/report/ShowReport/data?{szse_params}"
        last_error = None
        for attempt in range(3):
            try:
                szse_payload = json.loads(fetch_text(szse_url, "https://www.szse.cn/"))
                szse_value = number(szse_payload[0]["data"][0]["jrrzye"])
                if szse_value is None:
                    raise ValueError(f"SZSE financing balance missing for {day}")
                return day, sse_daily[day] + szse_value
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(1.0 * (attempt + 1))
        raise last_error

    failed = []
    # The bounded pool is only material during the one-time 2026 history migration.
    # Normal daily runs have one missing trading day and therefore make one SZSE request.
    workers = min(2, max(1, len(missing_days)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch_szse, day): day for day in missing_days}
        for future in as_completed(futures):
            day = futures[future]
            try:
                fetched_day, value = future.result()
                existing[fetched_day] = value
            except Exception as exc:
                failed.append(f"{day}: {exc}")
    return sorted(existing.items()), failed


def treasury(end):
    url = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/2026/all?type=daily_treasury_yield_curve&field_tdr_date_value=2026&page&_format=csv"
    records = list(csv.DictReader(io.StringIO(fetch_csv(url))))
    result = {key: [] for key in ("2y", "10y", "20y", "30y")}
    for row in records:
        day = normalize_date(row.get("Date"))
        if not day or day > end:
            continue
        for key, column in (("2y", "2 Yr"), ("10y", "10 Yr"), ("20y", "20 Yr"), ("30y", "30 Yr")):
            result[key].append((day, number(row.get(column))))
    return result


def fred(series_id, end):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={START}&coed={end}"
    output = []
    for row in csv.DictReader(io.StringIO(fetch_csv(url))):
        value = number(row.get(series_id))
        if value is not None:
            output.append((row.get("DATE") or row.get("observation_date"), value))
    return output


def retain(old, tab, series_id):
    tabs = [tab]
    if tab == "credit_pmi":
        tabs.extend(["credit_money", "pmi"])
    for candidate in tabs:
        for item in (old or {}).get("tabs", {}).get(candidate, {}).get("series", []):
            if item.get("id") == series_id:
                kept = dict(item); kept["refresh_status"] = "stale"; kept["note"] = "本次刷新失败，保留上次成功结果。"; return kept
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-date", default=date.today().isoformat())
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    end, old = args.target_date, load(OUTPUT, {}) or {}
    errors = {}
    ifind = {}
    if not args.offline:
        try:
            ifind = run_ifind(end, old)
            for key, message in ifind.get("errors", {}).items():
                errors[f"ifind_{key}"] = str(message)[:500]
        except Exception as exc: errors["ifind"] = str(exc)[:500]

    # Deposit changes reproduce the research definition: year-to-date balances are differenced monthly.
    deposit_rows = DEPOSIT_YTD
    deposit_remote_ok = False
    deposit_remote = find_values(ifind, "deposits", {"household": ("住户",), "nbfi": ("非银行",)}, monthly=True, scale=1e-12)
    if deposit_remote["household"] and deposit_remote["nbfi"]:
        by_date = {}
        for day, value in deposit_remote["household"]: by_date.setdefault(day, {})["household"] = value
        for day, value in deposit_remote["nbfi"]: by_date.setdefault(day, {})["nbfi"] = value
        complete = [(day, values["household"], values["nbfi"]) for day, values in by_date.items() if len(values) == 2]
        if complete:
            deposit_rows = sorted(complete)
            deposit_remote_ok = True
    monthly_household, monthly_nbfi = [], []
    previous_h = previous_n = 0.0
    for day, household_ytd, nbfi_ytd in deposit_rows:
        h, n = household_ytd - previous_h, nbfi_ytd - previous_n
        monthly_household.append((day, h)); monthly_nbfi.append((day, n))
        previous_h, previous_n = household_ytd, nbfi_ytd

    turnover_values = find_values(ifind, "turnover", {"shanghai": ("沪市", "成交"), "shenzhen": ("深市", "成交"), "total": ("沪深两市", "成交")}, scale=1e-8)
    margin_values = []
    if not args.offline:
        try:
            margin_values, margin_failures = exchange_margin_daily(
                end, old_series_points(old, "retail_flow", "margin_financing_balance")
            )
            if margin_failures:
                errors["exchange_margin_partial"] = "; ".join(margin_failures[:5])
        except Exception as exc: errors["exchange_margin"] = str(exc)[:500]
    money_values = find_values(ifind, "money", {"m1_yoy": ("M1",), "m2_yoy": ("M2",)}, monthly=True)
    credit_values = {"social_increment": find_values(ifind, "credit_increment", {"social_increment": ("增量",)}, monthly=True, scale=1e-12)["social_increment"],
                     "social_stock_yoy": find_values(ifind, "credit_stock", {"social_stock_yoy": ("存量", "同比")}, monthly=True)["social_stock_yoy"]}
    credit_structure_values = {
        "household_long_term_loan": find_values(ifind, "household_long_term", {"household_long_term_loan": ("住户", "中长期")}, monthly=True, scale=1e-12)["household_long_term_loan"],
        "enterprise_long_term_loan": find_values(ifind, "enterprise_long_term", {"enterprise_long_term_loan": ("企", "中长期贷款")}, monthly=True, scale=1e-12)["enterprise_long_term_loan"],
    }
    pmi_values = find_values(ifind, "pmi", {"manufacturing_pmi": ("制造业", "PMI"), "non_manufacturing_pmi": ("非制造业",), "composite_pmi": ("综合", "PMI")}, monthly=True)
    pmi_values["pmi_new_orders"] = find_values(ifind, "pmi_new_orders", {"pmi_new_orders": ("新订单",)}, monthly=True)["pmi_new_orders"]
    months = [month_end_date(f"2026-{month:02d}") for month in range(1, 8)]

    treasury_values = {}
    if not args.offline:
        try: treasury_values = treasury(end)
        except Exception as exc: errors["treasury"] = str(exc)[:500]
    fed_rate, dollar, dollar_note, dollar_source = [], [], "DXY主源", "ifind"
    dxy = find_values(ifind, "dxy", {"dxy": ("美元指数",)})["dxy"]
    fed_raw = find_values(ifind, "fed", {"upper": ("上限",), "lower": ("下限",)})
    fed_rate = fed_raw.get("upper", [])
    if dxy:
        dollar = dxy
    elif not args.offline:
        try:
            dollar = fred("DTWEXBGS", end); dollar_note = "DXY不可用，使用美联储广义贸易加权美元指数替代；两者不混接。"; dollar_source = "fred"
        except Exception as exc: errors["dollar"] = str(exc)[:500]
    if not fed_rate and not args.offline:
        try: fed_rate = fred("DFEDTARU", end)
        except Exception as exc: errors["fed_rate"] = str(exc)[:500]

    def series_or_old(tab, item):
        kept = retain(old, tab, item["id"])
        if item.get("points"):
            if kept:
                merged = {point.get("date"): dict(point) for point in kept.get("points", []) if point.get("date")}
                merged.update({point.get("date"): dict(point) for point in item.get("points", []) if point.get("date")})
                item["points"] = [merged[day] for day in sorted(merged)]
                for index, point in enumerate(item["points"]):
                    point["previous"] = item["points"][index - 1]["value"] if index else None
                item["latest"] = item["points"][-1]["value"]
                item["previous"] = item["points"][-2]["value"] if len(item["points"]) > 1 else None
                item["as_of"] = item["points"][-1]["date"]
            return item
        if kept:
            return kept
        item["refresh_status"] = "missing"
        item["note"] = "本次刷新未取得可用数据。"
        return item

    def monthly_or_old(tab, series_id, label, unit, values, source_key, seed=None, note=""):
        if values:
            return series_or_old(tab, make_series(series_id, label, unit, values, source_key, note=note))
        kept = retain(old, tab, series_id)
        if kept:
            return kept
        return make_series(series_id, label, unit, seed or [], source_key, note=note)

    if deposit_remote_ok:
        deposit_monthly_series = [
            series_or_old("retail_flow", make_series("household_deposit_change", "住户存款月增量", "万亿元", monthly_household, "pbc", note="由年内累计值逐月差分")),
            series_or_old("retail_flow", make_series("nbfi_deposit_change", "非银存款月增量", "万亿元", monthly_nbfi, "pbc", note="由年内累计值逐月差分")),
        ]
    else:
        deposit_monthly_series = [
            retain(old, "retail_flow", "household_deposit_change") or make_series("household_deposit_change", "住户存款月增量", "万亿元", monthly_household, "pbc", note="由年内累计值逐月差分"),
            retain(old, "retail_flow", "nbfi_deposit_change") or make_series("nbfi_deposit_change", "非银存款月增量", "万亿元", monthly_nbfi, "pbc", note="由年内累计值逐月差分"),
        ]
    deposit_series = deposit_monthly_series + [
        series_or_old("retail_flow", make_series("margin_financing_balance", "沪深两市融资余额", "亿元", margin_values, "margin_sources", note="日度；由ETF捕手每日任务更新至上一完整交易日；仅含沪深，不含北交所")),
    ]
    turnover_series = [series_or_old("retail_flow", make_series(key, label, "亿元", turnover_values[key], "ifind")) for key, label in (("shanghai", "沪市成交额"), ("shenzhen", "深市成交额"), ("total", "两市成交额"))]
    credit_series = [
        series_or_old("credit_pmi", make_series("social_increment", "社融增量", "万亿元", credit_values["social_increment"], "pbc")),
        series_or_old("credit_pmi", make_series("social_stock_yoy", "社融存量同比", "%", credit_values["social_stock_yoy"], "pbc")),
        monthly_or_old("credit_pmi", "m1_yoy", "M1同比", "%", money_values["m1_yoy"], "pbc", list(zip(months, MONEY_SEED["m1_yoy"]))),
        monthly_or_old("credit_pmi", "m2_yoy", "M2同比", "%", money_values["m2_yoy"], "pbc", list(zip(months, MONEY_SEED["m2_yoy"]))),
    ]
    structure_series = [monthly_or_old("credit_pmi", key, label, "万亿元", credit_structure_values[key], "pbc", list(zip(months, CREDIT_STRUCTURE_SEED[key]))) for key, label in (("household_long_term_loan", "住户中长期贷款当月新增"), ("enterprise_long_term_loan", "企业中长期贷款当月新增"))]
    social_by_month = {month_key(day): value for day, value in credit_values["social_increment"]}
    household_by_month = {month_key(day): value for day, value in credit_structure_values["household_long_term_loan"]}
    enterprise_by_month = {month_key(day): value for day, value in credit_structure_values["enterprise_long_term_loan"]}
    structure_share = []
    for month in sorted(set(social_by_month) & set(household_by_month) & set(enterprise_by_month)):
        share = structure_share_value(household_by_month[month], enterprise_by_month[month], social_by_month[month])
        if share is not None:
            structure_share.append((month_end_date(month), share))
    structure_series.append(make_series("long_term_loan_share", "居民与企业中长期贷款占新增社融", "%", structure_share, "pbc", note="社融增量不高于0.1万亿元时不计算，避免分母失真"))
    pmi_series = [monthly_or_old("credit_pmi", key, label, "指数", pmi_values[key], "nbs", list(zip(months, PMI_SEED[key]))) for key, label in (("manufacturing_pmi", "制造业PMI"), ("pmi_new_orders", "制造业PMI新订单"), ("non_manufacturing_pmi", "非制造业商务活动指数"), ("composite_pmi", "综合PMI产出指数"))]
    credit_pmi_series = credit_series + structure_series + pmi_series
    compass = build_compass({item["id"]: item for item in credit_pmi_series})
    yield_series = [series_or_old("overseas", make_series(f"ust_{key}", f"{key.upper()}美债收益率", "%", treasury_values.get(key, []), "treasury")) for key in ("2y", "10y", "20y", "30y")]
    by_ten = {p["date"]: p["value"] for p in yield_series[1].get("points", [])}; by_two = {p["date"]: p["value"] for p in yield_series[0].get("points", [])}
    spread = [(day, by_ten[day] - value) for day, value in by_two.items() if day in by_ten]
    overseas_series = yield_series + [
        series_or_old("overseas", make_series("ust_10y_2y_spread", "10Y-2Y期限利差", "百分点", spread, "treasury")),
        series_or_old("overseas", make_series("fed_target_upper", "美联储目标利率上限", "%", fed_rate, "fed" if fed_raw.get("upper") else "fred")),
        series_or_old("overseas", make_series("dollar_index", "DXY" if dollar_source == "ifind" else "广义贸易加权美元指数（替代）", "指数", dollar, dollar_source, note=dollar_note)),
    ]
    all_series = deposit_series + turnover_series + credit_pmi_series + overseas_series
    stale_ids = [item["id"] for item in all_series if item.get("refresh_status") != "success"]
    if stale_ids:
        errors["stale_series"] = ",".join(stale_ids)
    payload = {
        "schema_version": 1, "start_date": START, "generated_at": datetime.now().astimezone().isoformat(),
        "target_date": end, "refresh_status": "partial" if errors else "success", "errors": errors,
        "tabs": {
            "retail_flow": {"label": "散户资金流", "series": deposit_series + turnover_series},
            "credit_pmi": {"label": "社融与PMI", "reference_lines": [{"value": 50, "label": "荣枯线"}], "compass": compass, "series": credit_pmi_series},
            "overseas": {"label": "海外变量", "series": overseas_series, "events": [{"date": day, "label": label, **source("fed")} for day, label in FOMC_2026]},
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUTPUT.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, OUTPUT)
    print(json.dumps({"status": payload["refresh_status"], "file": str(OUTPUT), "errors": errors}, ensure_ascii=False))


if __name__ == "__main__":
    main()
