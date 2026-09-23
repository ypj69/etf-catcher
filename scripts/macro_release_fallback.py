"""Verified PBC releases as a bounded, auditable monthly data fallback.

Sources are registered explicitly; missing future releases still fail freshness.
Never mix rounded published cumulative totals with higher precision monthly data.
"""
from __future__ import annotations

import calendar
import html
import json
import re
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

ALLOWED_HOSTS = {"www.xinhuanet.com", "jrj.sh.gov.cn", "www.pbc.gov.cn"}
MONTHLY_IDS = {
    "household_deposit_change", "nbfi_deposit_change", "social_increment",
    "social_stock_yoy", "m1_yoy", "m2_yoy", "household_long_term_loan",
    "enterprise_long_term_loan",
}


def month_end(month):
    year, number = map(int, month.split("-"))
    return f"{month}-{calendar.monthrange(year, number)[1]:02d}"


def parse_report(document, month):
    text = re.sub(r"<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>", "", document, flags=re.S | re.I)
    text = re.sub(r"\s+", "", html.unescape(re.sub(r"<[^>]+>", "", text)))
    text = text.replace("（", "(").replace("）", ")")
    year, number = map(int, month.split("-"))
    if f"{year}年{number}月金融统计数据报告" not in text or "中国人民银行" not in text:
        raise ValueError(f"Unverified PBC report for {month}")

    def amount(pattern):
        match = re.search(pattern + r"(增加|减少)?(\d+(?:\.\d+)?)(万亿元|亿元|%)", text)
        if not match:
            raise ValueError(f"Missing report field: {pattern}")
        direction, value, unit = match.groups()
        value = Decimal(value) * (-1 if direction == "减少" else 1)
        return value / 10000 if unit == "亿元" else value

    def growth(label):
        match = re.search(label + r"[^。]*?同比增长(\d+(?:\.\d+)?)%", text)
        if not match:
            raise ValueError(f"Missing growth field: {label}")
        return Decimal(match.group(1))

    return {
        "household": amount(r"住户存款"),
        "nbfi": amount(r"非银行业金融机构存款"),
        "social_ytd": amount(r"社会融资规模增量累计为"),
        "household_loan_ytd": amount(r"住户贷款[^。]*?其中[^。]*?中长期贷款"),
        "enterprise_loan_ytd": amount(r"企\(事\)业单位贷款[^。]*?其中[^。]*?中长期贷款"),
        "m1_yoy": growth(r"狭义货币\(M1\)"),
        "m2_yoy": growth(r"广义货币\(M2\)"),
        "social_stock_yoy": growth(r"社会融资规模存量为"),
    }


def release_tables(registry, target_date, fetch, archive=None):
    eligible = [report for report in registry.get("reports", [])
                if report["published_at"] <= target_date and month_end(report["month"]) <= target_date]
    reports = {}
    for report in sorted(eligible, key=lambda item: item["month"])[-2:]:
        url = report["url"]
        if urlparse(url).scheme != "https" or urlparse(url).hostname not in ALLOWED_HOSTS:
            raise ValueError("Untrusted macro report URL")
        cache = Path(archive) / f"{report['month']}.html" if archive else None
        document = cache.read_text(encoding="utf-8") if cache and cache.exists() else fetch(url)
        parsed = parse_report(document, report["month"])
        if cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(document, encoding="utf-8")
            cache.with_suffix(".source.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        reports[report["month"]] = (parsed, report)
    if len(reports) != 2:
        raise ValueError("Two consecutive verified monthly releases are required")
    previous_month, current_month = sorted(reports)
    py, pm = map(int, previous_month.split("-"))
    cy, cm = map(int, current_month.split("-"))
    if cy * 12 + cm - py * 12 - pm != 1:
        raise ValueError("Nonconsecutive macro releases")
    previous, previous_source = reports[previous_month]
    current, current_source = reports[current_month]
    day = month_end(current_month)

    def table(column_values):
        return [{"columns": ["日期", *column_values], "rows": [{"日期": day, **column_values}]}]

    yuan = lambda value: float(value * Decimal("1e12"))
    tables = {
        "deposits": table({"住户存款累计增加额": yuan(current["household"]), "非银行存款累计增加额": yuan(current["nbfi"])}),
        "credit_increment": table({"社融增量": yuan(current["social_ytd"] - previous["social_ytd"])}),
        "credit_stock": table({"社融存量同比": float(current["social_stock_yoy"])}),
        "money": table({"M1同比": float(current["m1_yoy"]), "M2同比": float(current["m2_yoy"])}),
        "household_long_term": table({"住户中长期贷款": yuan(current["household_loan_ytd"] - previous["household_loan_ytd"])}),
        "enterprise_long_term": table({"企业中长期贷款": yuan(current["enterprise_loan_ytd"] - previous["enterprise_loan_ytd"])}),
    }
    provenance = {
        "month": current_month, "source_url": current_source["url"],
        "previous_source_url": previous_source["url"], "published_at": current_source["published_at"],
        "method": "央行报告备用源；累计指标按相邻报告累计值差分，保留报告披露精度（非接口原值精度）",
    }
    return tables, provenance
