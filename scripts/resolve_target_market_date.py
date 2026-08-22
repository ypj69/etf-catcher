from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from update_indices import call_ifind, parse_rows  # noqa: E402


TENCENT_ENDPOINT = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"


def calendar_chunks(start: date, end: date, days: int = 300):
    cursor = start
    while cursor <= end:
        chunk_end = min(end, cursor + timedelta(days=days - 1))
        yield cursor, chunk_end
        cursor = chunk_end + timedelta(days=1)


def parse_tencent_sessions(text: str, start: date, end: date) -> list[date]:
    payload = json.loads(text)
    node = payload.get("data", {}).get("sh000300", {})
    rows = node.get("qfqday") or node.get("day") or []
    sessions: set[date] = set()
    for row in rows:
        try:
            candidate = date.fromisoformat(str(row[0])[:10])
            close = float(row[2])
        except (IndexError, TypeError, ValueError):
            continue
        if start <= candidate <= end and close > 0:
            sessions.add(candidate)
    return sorted(sessions)


def tencent_sessions(start: date, end: date) -> list[date]:
    if start > end:
        return []
    sessions: set[date] = set()
    for chunk_start, chunk_end in calendar_chunks(start, end):
        limit = max(20, (chunk_end - chunk_start).days + 20)
        query = urllib.parse.urlencode(
            {
                "param": (
                    f"sh000300,day,{chunk_start.isoformat()},"
                    f"{chunk_end.isoformat()},{limit},qfq"
                )
            }
        )
        request = urllib.request.Request(
            f"{TENCENT_ENDPOINT}?{query}",
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"},
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            text = response.read().decode("utf-8", errors="ignore")
        sessions.update(parse_tencent_sessions(text, chunk_start, chunk_end))
    return sorted(sessions)


def ifind_sessions(start: date, end: date) -> list[date]:
    """Return only exchange sessions actually present in iFinD index history."""
    if start > end:
        return []
    sessions: set[date] = set()
    for chunk_start, chunk_end in calendar_chunks(start, end, days=31):
        query = (
            f"查询上证指数(000001.SH)在{chunk_start.isoformat()}至{chunk_end.isoformat()}逐交易日的收盘点位，"
            "必须逐日返回证券代码、日期和收盘点位；休市日不要返回。"
        )
        rows = parse_rows(call_ifind(query))
        chunk_sessions = {
            row["date"].date()
            for row in rows
            if row.get("index_code") == "000001.SH"
            and row.get("close") is not None
            and chunk_start <= row["date"].date() <= chunk_end
        }
        if not chunk_sessions and (chunk_end - chunk_start).days >= 13:
            raise RuntimeError(
                f"iFinD returned no parseable Shanghai Composite sessions for "
                f"{chunk_start.isoformat()} to {chunk_end.isoformat()}"
            )
        sessions.update(chunk_sessions)
    return sorted(sessions)


def actual_sessions(start: date, end: date) -> tuple[list[date], str]:
    """Use independent real-session sources; never guess with weekdays."""
    if start > end:
        return [], "no range"
    errors: list[str] = []
    try:
        sessions = tencent_sessions(start, end)
        if sessions:
            return sessions, "Tencent CSI 300 actual daily sessions"
    except Exception as exc:
        errors.append(f"Tencent: {exc}")
    try:
        sessions = ifind_sessions(start, end)
        return sessions, "iFinD Shanghai Composite actual sessions"
    except Exception as exc:
        errors.append(f"iFinD: {exc}")
    raise RuntimeError("No reliable A-share trading calendar source: " + " | ".join(errors))


def latest_ifind_session(as_of: date) -> date:
    sessions = ifind_sessions(as_of - timedelta(days=15), as_of - timedelta(days=1))
    if not sessions:
        raise RuntimeError("iFinD returned no parseable Shanghai Composite sessions")
    return sessions[-1]


def latest_actual_session(as_of: date) -> tuple[date, str]:
    sessions, source = actual_sessions(
        as_of - timedelta(days=20), as_of - timedelta(days=1)
    )
    if not sessions:
        raise RuntimeError(
            "No parseable completed A-share session; update stopped to avoid guessing a holiday"
        )
    return sessions[-1], source


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default=str(ROOT / "data" / "etf_flow.sqlite3"))
    parser.add_argument("--as-of", default=date.today().isoformat())
    args = parser.parse_args()
    if not Path(args.database).is_file():
        raise FileNotFoundError(f"Database not found: {args.database}")
    target, _source = latest_actual_session(date.fromisoformat(args.as_of))
    print(target.isoformat())


if __name__ == "__main__":
    main()