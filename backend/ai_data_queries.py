"""Bounded, parameterized, read-only queries for the panel's AI assistant."""
from __future__ import annotations

import json
import re
from datetime import date

CORE_ETFS = ("510300", "510310", "510330", "159919")
DATE_RE = re.compile(r"(?:(\d{4})\s*[-/年]\s*)?(\d{1,2})\s*[-/月]\s*(\d{1,2})(?:日|号)?")
RANK_RE = re.compile(r"前\s*([0-9]{1,3}|[一二两三四五六七八九十百]+)|top\s*([0-9]{1,3})", re.I)


def date_range(question: str, latest: str) -> tuple[str, str] | None:
    """Missing years use the latest published panel year, never the model's clock."""
    matches = list(DATE_RE.finditer(question))
    if not matches:
        year = re.search(r"(20\d{2})年(?:以来|全年|年初至今)", question)
        if year:
            return f"{year[1]}-01-01", min(latest, f"{year[1]}-12-31")
        return None
    if len(matches) > 2:
        raise ValueError("请每次查询一个日期或一个连续日期区间")
    inherited_year = int(next((m[1] for m in matches if m[1]), latest[:4]))
    dates = []
    for match in matches:
        inherited_year = int(match[1] or inherited_year)
        dates.append(date(inherited_year, int(match[2]), int(match[3])).isoformat())
    if len(dates) == 1:
        return dates[0], dates[0]
    if dates[0] > dates[1]:
        # Infer a year rollover only when the second year was omitted.
        if not matches[1][1]:
            dates[1] = date(int(dates[1][:4]) + 1, int(matches[1][2]), int(matches[1][3])).isoformat()
        else:
            raise ValueError("起始日期不能晚于结束日期")
    return dates[0], dates[1]


def chinese_number(value: str) -> int:
    if value.isdigit():
        return int(value)
    digits = dict(zip("一二两三四五六七八九", (1, 2, 2, 3, 4, 5, 6, 7, 8, 9)))
    if value == "百":
        return 100
    if "十" in value:
        left, right = value.split("十", 1)
        return digits.get(left, 1) * 10 + digits.get(right, 0)
    return digits.get(value, 10)


def ranking_request(question: str) -> tuple[int, bool] | None:
    match = RANK_RE.search(question)
    if not match or not re.search(r"ETF|基金", question, re.I):
        return None
    if not re.search(r"净流入|净流出|资金流|流入最多|流出最多", question):
        return None
    return max(1, min(100, chinese_number(match[1] or match[2]))), bool(re.search(r"净流出|流出最多", question))


def core_request(question: str) -> bool:
    return bool(re.search(r"国家队|稳定资金|核心沪深\s*300|四只.*300|4只.*300", question))


def query_dates(conn, question: str, window: int, published: str | None):
    latest = conn.execute("SELECT MAX(trade_date) FROM etf_daily WHERE trade_date<=?", (published or "9999-12-31",)).fetchone()[0]
    if not latest:
        raise ValueError("本地没有已发布的ETF日频记录")
    requested = date_range(question, latest)
    if requested:
        start, end = requested
    else:
        single = bool(re.search(r"最近一天|最新一天|最近一日|上一交易日|最新交易日|今天|当日", question))
        end = latest
        relative = bool(re.search(r"\d+\s*(?:个)?(?:交易日|天)|一年|全年|半年|季度|个月|月度", question))
        start = conn.execute("SELECT MIN(trade_date) FROM (SELECT DISTINCT trade_date FROM etf_daily WHERE trade_date<=? ORDER BY trade_date DESC LIMIT ?)", (end, 1 if single or (ranking_request(question) and not relative) else window)).fetchone()[0]
    dates = [r[0] for r in conn.execute("SELECT DISTINCT trade_date FROM etf_daily WHERE trade_date BETWEEN ? AND ? ORDER BY trade_date", (start, min(end, latest)))]
    return start, min(end, latest), {"requested_start": start, "requested_end": end, "published_latest": latest,
        "start": dates[0] if dates else None, "end": dates[-1] if dates else None,
        "trading_days": len(dates), "explicit_dates": bool(requested), "unavailable_after": latest if end > latest else None}


def flow_summary(conn, code: str, start: str, end: str, expected: int) -> dict:
    row = dict(conn.execute("""SELECT MIN(trade_date) AS start,MAX(trade_date) AS end,
        COUNT(*) AS rows,COUNT(net_flow) AS valid_flow_rows,SUM(net_flow) AS net_flow
        FROM etf_daily WHERE etf_code=? AND trade_date BETWEEN ? AND ?""", (code, start, end)).fetchone())
    row["missing_flow_days"] = expected - row["valid_flow_rows"]
    row["complete"] = row["missing_flow_days"] == 0 and expected > 0
    row["net_flow_yi"] = row["net_flow"] / 1e8 if row["net_flow"] is not None else None
    return row


def flow_ranking(conn, start: str, end: str, days: int, limit: int, outflow: bool) -> dict:
    direction, sign = ("ASC", "<") if outflow else ("DESC", ">")
    # Only complete observations rank across an interval; disclose exclusions.
    base = """SELECT d.etf_code,m.etf_name,COUNT(d.net_flow) AS valid_flow_rows,
        SUM(d.net_flow) AS net_flow,MIN(d.trade_date) AS start,MAX(d.trade_date) AS end
        FROM etf_daily d JOIN etf_master m ON m.etf_code=d.etf_code
        WHERE m.enabled=1 AND d.trade_date BETWEEN ? AND ? GROUP BY d.etf_code"""
    rows = [dict(r) for r in conn.execute(f"SELECT * FROM ({base}) WHERE valid_flow_rows=? AND net_flow {sign} 0 ORDER BY net_flow {direction},etf_code LIMIT ?", (start, end, days, limit))] if days else []
    counts = conn.execute(f"SELECT COUNT(*),SUM(CASE WHEN valid_flow_rows=? THEN 1 ELSE 0 END) FROM ({base})", (days, start, end)).fetchone()
    for rank, row in enumerate(rows, 1):
        row.update(rank=rank, net_flow_yi=row["net_flow"] / 1e8)
    return {"type": "ETF净流出排名" if outflow else "ETF净流入排名", "source": "data/etf_catcher.sqlite3/etf_daily.net_flow",
        "units": {"net_flow": "元", "net_flow_yi": "亿元"}, "start": start, "end": end, "requested_top": limit,
        "sample": "当前启用ETF；区间每个交易日净流入均非空；仅列所问方向的产品，不足不补位",
        "observed_etfs": counts[0], "eligible_etfs": counts[1] or 0, "excluded_incomplete_etfs": counts[0] - (counts[1] or 0), "rows": rows}


def encode_context(sections: list[dict], coverage: dict, limit: int = 88000) -> str:
    """Keep computed totals and ranks intact; disclose any omitted time series."""
    def encode():
        return json.dumps(sections, ensure_ascii=False, separators=(",", ":"))
    encoded = encode()
    omissions = []
    while len(encoded) > limit:
        candidates = [s for s in sections if len(s.get("rows", [])) > 20 and "排名" not in s["type"]]
        if not candidates:
            raise ValueError("所选数据超过问答容量，请缩短日期区间或减少比较对象")
        section = max(candidates, key=lambda s: len(json.dumps(s, ensure_ascii=False)))
        if "delivery" not in section:
            section["delivery"] = {"total_rows": len(section["rows"]), "note": "上下文容量限制，保留首条和最近明细；区间合计仍用完整区间计算，不能据展示行推算全区间趋势"}
            omissions.append(section["type"] + ":" + str(section.get("meta", {}).get("etf_code", section.get("name", ""))))
        section["rows"] = section["rows"][:1] + section["rows"][-max(19, len(section["rows"]) // 2):]
        section["delivery"]["delivered_rows"] = len(section["rows"])
        encoded = encode()
    coverage["omitted_series"] = omissions
    coverage["context_chars"] = len(encoded)
    return encoded
