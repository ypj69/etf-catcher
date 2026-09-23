from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from ai_data_queries import CORE_ETFS, core_request, encode_context, flow_ranking, flow_summary, query_dates, ranking_request


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
WEB_DATA = ROOT / "data" / "web"
DATABASE = ROOT / "data" / "etf_catcher.sqlite3"
BASELINE = ROOT / "config" / "production_baseline.json"
CODE_RE = re.compile(r"^\d{6}$")
ANY_CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def model_setting(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def ifind_skill_dir() -> Path:
    return Path(os.environ.get("IFIND_SKILL_DIR", Path.home() / ".codex" / "skills" / "ifind-finance-data"))


def database_dates() -> dict:
    if not DATABASE.exists():
        return {"market_latest": None, "flow_latest": None, "rows": 0}
    with sqlite3.connect(f"file:{DATABASE.as_posix()}?mode=ro", uri=True, timeout=8) as connection:
        market, flow, rows = connection.execute(
            "SELECT MAX(CASE WHEN close IS NOT NULL THEN trade_date END), "
            "MAX(CASE WHEN net_flow IS NOT NULL THEN trade_date END), COUNT(*) FROM etf_daily"
        ).fetchone()
    return {"market_latest": market, "flow_latest": flow, "rows": int(rows)}


def research_window(question: str) -> int:
    match = re.search(r"近?\s*(\d{1,4})\s*(?:个)?交易日", question)
    if match:
        return max(5, min(500, int(match.group(1))))
    if "一年" in question or "全年" in question:
        return 250
    if "半年" in question:
        return 120
    if "季度" in question or "三个月" in question:
        return 60
    if "一个月" in question or "月度" in question:
        return 25
    return 60


def group_aliases(name: str) -> list[str]:
    aliases = [name, *re.findall(r"[（(]([^）)]+)[）)]", name)]
    generic = {"ETF", "指数", "行业", "主题", "策略", "综合", "其他", "宽基", "资产"}
    return [item.strip() for item in aliases if len(item.strip()) >= 2 and item.strip() not in generic]


def matched_groups(question: str, names: list[str], limit: int = 5) -> list[str]:
    ranked = []
    for name in dict.fromkeys(names):
        matched = [alias for alias in group_aliases(name) if alias in question]
        if matched:
            ranked.append((name in question, max(map(len, matched)), len(name), name))
    ranked.sort(reverse=True)
    return [item[-1] for item in ranked[:limit]]


def local_research_context(body: dict, question: str) -> tuple[str, dict]:
    if not DATABASE.exists():
        raise FileNotFoundError("本地种子数据库尚未安装")
    window = research_window(question)
    explicit = [str(body.get("etf_code", ""))] if CODE_RE.fullmatch(str(body.get("etf_code", ""))) and re.search(r"这只|当前ETF|该ETF|当前基金", question) else []
    codes = list(dict.fromkeys(ANY_CODE_RE.findall(question) + explicit))[:4]
    ranking = ranking_request(question)
    is_core = core_request(question)
    if is_core:
        codes = list(CORE_ETFS)
    elif ranking:
        codes = []
    sections: list[dict] = []
    coverage = {"database": "data/etf_catcher.sqlite3", "window": window, "etfs": [], "groups": [], "indices": []}
    with sqlite3.connect(f"file:{DATABASE.as_posix()}?mode=ro", uri=True, timeout=8) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        published = (load_json(WEB_DATA / "meta.json", {}) or {}).get("flow_latest")
        start, end, bounds = query_dates(connection, question, window, published)
        coverage["date_range"] = bounds
        coverage["query_version"] = "20260923"
        sections.append({"type": "查询范围与口径", **bounds, "note": "区间包含首尾交易日，缺失不填零。单只ETF不得使用全市场数值代替。金额字段为元，net_flow_yi为亿元。"})
        masters = [dict(row) for row in connection.execute(
            "SELECT etf_code,etf_name,exchange,asset_class,category_l1,category_l2,tracking_index_code,tracking_index_name "
            "FROM etf_master WHERE enabled=1"
        )]
        for row in masters:
            if not ranking and not is_core and row.get("etf_name") and row["etf_name"] in question and row["etf_code"] not in codes:
                codes.append(row["etf_code"])
            if len(codes) >= 4:
                break
        by_code = {row["etf_code"]: row for row in masters}
        for code in codes[:4]:
            meta = by_code.get(code)
            if not meta:
                continue
            rows = [dict(row) for row in connection.execute(
                "SELECT trade_date,close,pct_change,fund_share,fund_scale,net_flow,amount,flow_source,data_status "
                "FROM etf_daily WHERE etf_code=? AND trade_date BETWEEN ? AND ? ORDER BY trade_date DESC", (code, start, end)
            )][::-1]
            summary = flow_summary(connection, code, start, end, bounds["trading_days"])
            sections.append({"type": "ETF历史", "meta": meta, "rows": rows, "summary": summary})
            coverage["etfs"].append({"code": code, "name": meta["etf_name"], "start": rows[0]["trade_date"] if rows else None, "end": rows[-1]["trade_date"] if rows else None, "rows": len(rows)})
        if ranking:
            rank = flow_ranking(connection, start, end, bounds["trading_days"], *ranking)
            sections.append(rank)
            coverage["ranking"] = {k: v for k, v in rank.items() if k != "rows"}
            coverage["ranking"]["returned_rows"] = len(rank["rows"])
        if is_core:
            summaries = [flow_summary(connection, code, start, end, bounds["trading_days"]) for code in CORE_ETFS]
            totals = [row["net_flow"] for row in summaries if row["net_flow"] is not None]
            sections.append({"type": "四只核心沪深300ETF区间合计", "codes": list(CORE_ETFS),
                "net_flow": sum(totals) if totals else None, "by_etf": dict(zip(CORE_ETFS, summaries)),
                "complete": all(row["complete"] for row in summaries),
                "note": "仅为稳定资金行为代理，不等同国家队实际买卖；不完整时合计只包含已知部分。"})
        overall = [dict(row) for row in connection.execute(
            "SELECT trade_date,SUM(net_flow) AS net_flow,SUM(amount) AS amount,COUNT(*) AS etf_rows "
            "FROM etf_daily WHERE trade_date BETWEEN ? AND ? "
            "GROUP BY trade_date ORDER BY trade_date", (start, end)
        )]
        sections.append({"type": "全市场ETF历史", "rows": overall})
        table_names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "panel_group_daily" in table_names:
            names = [row[0] for row in connection.execute("SELECT DISTINCT group_name FROM panel_group_daily")]
            for name in matched_groups(question, names):
                rows = [dict(row) for row in connection.execute(
                    "SELECT * FROM panel_group_daily WHERE group_name=? AND trade_date BETWEEN ? AND ? ORDER BY trade_date DESC", (name, start, end)
                )][::-1]
                sections.append({"type": "分类历史（与网页面板一致）", "name": name, "rows": rows})
                coverage["groups"].append({"name": name, "start": rows[0]["trade_date"] if rows else None, "end": rows[-1]["trade_date"] if rows else None, "rows": len(rows)})
        if "index_daily" in table_names and re.search(r"全球|海外|美股|美国|日韩|指数|标普|纳指|上证|市场情绪", question):
            dates = [row[0] for row in connection.execute("SELECT DISTINCT date FROM index_daily WHERE date BETWEEN ? AND ? ORDER BY date DESC", (start, end))]
            if dates:
                placeholders = ",".join("?" for _ in dates)
                indices = [dict(row) for row in connection.execute(
                    f"SELECT date,index_code,index_name,close,change_pct,normalized,source FROM index_daily WHERE date IN ({placeholders}) ORDER BY date,index_code", dates
                )]
                sections.append({"type": "全球指数历史", "rows": indices})
                coverage["indices"] = sorted({row["index_code"] for row in indices})
        if "macro_payload" in table_names and re.search(r"宏观|PMI|社融|货币|存款|信贷|利率|美债|美元|汇率|成交额|融资|流动性", question, re.I):
            row = connection.execute("SELECT payload_json FROM macro_payload WHERE id=1").fetchone()
            if row:
                macro = json.loads(row[0])
                for tab in macro.get("tabs", {}).values():
                    for series in tab.get("series", []):
                        points = series.get("points", [])
                        if bounds["explicit_dates"]:
                            points = [point for point in points if start <= str(point.get("date")) <= end]
                        series["points"] = points[-min(60, window):]
                sections.append({"type": "宏观监控", "data": macro})
                coverage["macro_as_of"] = macro.get("target_date")
    return encode_context(sections, coverage), coverage


def ifind_skill_ready() -> bool:
    skill = ifind_skill_dir()
    return (skill / "call-node.js").is_file() or (skill / "call.py").is_file()


def ifind_node_ready() -> bool:
    return bool(shutil.which("node")) and (ifind_skill_dir() / "call-node.js").is_file()


def run_ifind_detail(code: str, timeout: int = 75) -> dict:
    skill = ifind_skill_dir()
    node = shutil.which("node")
    if node and (skill / "call-node.js").is_file():
        command = [node, str(ROOT / "backend" / "ifind_detail.js"), code]
    elif (skill / "call.py").is_file():
        command = [sys.executable, str(ROOT / "backend" / "ifind_detail.py"), code]
    else:
        raise RuntimeError("未检测到可用的 iFinD Skill（call-node.js 或 call.py）")
    process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=timeout, check=True, env=os.environ.copy())
    return json.loads(process.stdout)


def online_research(question: str, body: dict) -> tuple[list, str | None]:
    if not body.get("online", True) or not re.search(r"联网|搜索|查(?:一下|找)|最新|近期|今天|政策|新闻|事件|会议|概率|FedWatch", question, re.I):
        return [], None
    code = next(iter(ANY_CODE_RE.findall(question)), "")
    try:
        process = subprocess.run(
            ["node", str(ROOT / "backend" / "ifind_ai_research.js")],
            input=json.dumps({"question": question, "subject": code}, ensure_ascii=False),
            capture_output=True, text=True, encoding="utf-8", timeout=55, check=True, env=os.environ.copy(),
        )
        return json.loads(process.stdout).get("results", [])[:2], None
    except subprocess.TimeoutExpired:
        return [], "iFinD联网查询超时，已仅使用本地数据库"
    except Exception as exc:
        return [], f"iFinD联网查询失败，已仅使用本地数据库：{str(exc)[:200]}"


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("[web]", fmt % args)

    def send_bytes(self, payload: bytes, content_type: str, status: int = 200):
        if (content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}) and "charset=" not in content_type:
            content_type += "; charset=utf-8"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def send_json(self, value, status: int = 200):
        self.send_bytes(json.dumps(value, ensure_ascii=False).encode(), "application/json", status)

    def body(self, limit: int = 200_000):
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0 or length > limit:
            raise ValueError("请求内容为空或过大")
        return json.loads(self.rfile.read(length).decode())

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/system/baseline":
            return self.send_json(load_json(BASELINE, {}))
        if parsed.path in {"/api/setup/status", "/api/system/health"}:
            dates = database_dates()
            payload = {"status": "ready" if dates["rows"] else "setup_required", "database": DATABASE.exists(), **dates, "data_policy": "latest_previous_complete_trading_day", "data_policy_zh": "最新上一个完整交易日", "schedule_not_before": "08:30", "ifind_skill": ifind_skill_ready(), "deepseek": bool(model_setting("DEEPSEEK_API_KEY")), "last_update": load_json(ROOT / "runtime" / "update_status.json", {})}
            return self.send_json(payload)
        if parsed.path == "/api/ai/status":
            return self.send_json({"configured": bool(model_setting("DEEPSEEK_API_KEY")), "model": model_setting("DEEPSEEK_MODEL", "deepseek-chat"), "local_database": DATABASE.exists(), "online_search": ifind_node_ready(), "default_history_days": 60})
        if parsed.path == "/api/etf/detail":
            return self.etf_detail(parse_qs(parsed.query).get("code", [""])[0])
        if parsed.path.startswith("/data/"):
            path, root = (WEB_DATA / parsed.path.removeprefix("/data/")).resolve(), WEB_DATA.resolve()
        else:
            path, root = (FRONTEND / ("index_v2.html" if parsed.path in {"", "/"} else parsed.path.lstrip("/"))).resolve(), FRONTEND.resolve()
        if root not in path.parents and path != root:
            return self.send_error(403)
        if not path.is_file():
            return self.send_error(404)
        self.send_bytes(path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream")

    def do_POST(self):
        try:
            body = self.body()
            if urlparse(self.path).path == "/api/ai/chat":
                return self.ai_chat(body)
            return self.send_error(404)
        except (ValueError, json.JSONDecodeError) as exc:
            return self.send_json({"error": str(exc)}, 400)

    def etf_detail(self, code: str):
        code = code.strip()
        if not CODE_RE.fullmatch(code):
            return self.send_json({"error": "ETF代码格式无效"}, 400)
        try:
            result = run_ifind_detail(code)
            self.send_json({"code": code, "live": result, "source": "当前用户的iFinD账户"})
        except subprocess.TimeoutExpired:
            self.send_json({"error": "iFinD查询超时，请稍后重试"}, 504)
        except Exception as exc:
            self.send_json({"error": f"iFinD查询失败：{exc}"}, 502)

    def ai_chat(self, body: dict):
        key = model_setting("DEEPSEEK_API_KEY")
        question = str(body.get("question", "")).strip()
        if not key:
            return self.send_json({"error": "尚未配置本机DeepSeek API Key"}, 503)
        if not question or len(question) > 3000:
            return self.send_json({"error": "问题为空或超过3000字"}, 400)
        try:
            local_context, coverage = local_research_context(body, question)
        except Exception as exc:
            return self.send_json({"error": f"本地数据库检索失败：{exc}"}, 500)
        online, warning = online_research(question, body)
        system = "你是ETF捕手研究助手。优先使用本地ETF、分类、指数和宏观数据；仅在本地不足、最新政策新闻或用户明确要求时使用联网结果。严格使用记录自己的日期，区分本地和联网来源，不把相关性说成因果，不生成保证收益的建议。先给结论，再用简洁小标题或项目符号，控制在1200字以内。"
        user = "本地研究数据：\n" + local_context
        if online:
            user += "\n\n联网补充：\n" + json.dumps(online, ensure_ascii=False)
        if warning:
            user += "\n\n联网提示：" + warning
        user += "\n\n用户问题：" + question
        payload = {"model": model_setting("DEEPSEEK_MODEL", "deepseek-chat"), "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "max_tokens": 2400}
        request = urllib.request.Request(model_setting("DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions"), data=json.dumps(payload, ensure_ascii=False).encode(), headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
        try:
            result = None
            for attempt in range(2):
                try:
                    with urllib.request.urlopen(request, timeout=110) as response:
                        result = json.loads(response.read().decode())
                    break
                except urllib.error.HTTPError:
                    raise
                except Exception:
                    if attempt == 0:
                        time.sleep(1.2)
            if result is None:
                raise RuntimeError("DeepSeek未返回结果")
            answer = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            self.send_json({"answer": answer, "model": result.get("model"), "usage": result.get("usage", {}), "sources": [{"name": "本地研究数据", "coverage": coverage}, *online], "warning": warning})
        except urllib.error.HTTPError as exc:
            self.send_json({"error": f"DeepSeek API错误 {exc.code}"}, 502)
        except Exception as exc:
            self.send_json({"error": f"DeepSeek调用失败：{exc}"}, 502)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
