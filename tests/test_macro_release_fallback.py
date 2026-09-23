import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from macro_release_fallback import parse_report, release_tables
from macro_freshness import evaluate_macro_freshness


def report(month, h, n, social, house_loan, enterprise_loan):
    number = int(month[5:7])
    return f"""<h1>2026年{number}月金融统计数据报告</h1>来源：中国人民银行
    社会融资规模存量为400万亿元，同比增长7.2%。
    社会融资规模增量累计为{social}万亿元。
    广义货币(M2)余额300万亿元，同比增长7.5%。狭义货币(M1)余额100万亿元，同比增长4.1%。
    住户存款增加{h}万亿元，非银行业金融机构存款增加{n}万亿元。
    住户贷款减少1万亿元，其中短期贷款减少1万亿元，中长期贷款增加{house_loan}亿元；
    企（事）业单位贷款增加10万亿元，其中短期贷款增加4万亿元，中长期贷款增加{enterprise_loan}万亿元。"""


def test_verified_cumulative_releases_preserve_units_and_signs():
    documents = {
        "https://jrj.sh.gov.cn/july": report("2026-07", 6.95, 5.76, 22.25, 1010, 5.32),
        "https://www.xinhuanet.com/august": report("2026-08", 6.99, 6.32, 23.91, 188, 5.64),
    }
    registry = {"reports": [
        {"month": "2026-07", "published_at": "2026-08-17", "url": "https://jrj.sh.gov.cn/july"},
        {"month": "2026-08", "published_at": "2026-09-14", "url": "https://www.xinhuanet.com/august"},
    ]}
    tables, provenance = release_tables(registry, "2026-09-15", documents.__getitem__)
    assert tables["credit_increment"][0]["rows"][0]["社融增量"] == 1.66e12
    assert tables["household_long_term"][0]["rows"][0]["住户中长期贷款"] == -8.22e10
    assert tables["enterprise_long_term"][0]["rows"][0]["企业中长期贷款"] == 3.2e11
    assert tables["deposits"][0]["rows"][0]["日期"] == "2026-08-31"
    assert provenance["previous_source_url"] == "https://jrj.sh.gov.cn/july"
    with pytest.raises(ValueError, match="Two consecutive"):
        release_tables(registry, "2026-09-13", documents.__getitem__)


def test_report_identity_and_missing_field_cannot_pass():
    text = report("2026-08", 1, 2, 3, 4, 5)
    with pytest.raises(ValueError, match="Unverified"):
        parse_report(text, "2026-07")
    with pytest.raises(ValueError, match="Missing"):
        parse_report(text.replace("住户存款", "其他存款"), "2026-08")


def test_calendar_due_is_not_reported_as_verified_peer_publication():
    assessment = evaluate_macro_freshness({"tabs": {"x": {"series": [
        {"id": "m1_yoy", "as_of": "2026-07-31"}, {"id": "m2_yoy", "as_of": "2026-07-31"}
    ]}}}, "2026-09-15")
    assert assessment["checks"]["m1_yoy"]["status"] == "stale"
    assert "保守发布时间窗" in assessment["checks"]["m1_yoy"]["reason"]
    assert "同批指标已发布" not in assessment["checks"]["m1_yoy"]["reason"]
