from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


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
    explicit = [str(body.get("etf_code", ""))] if CODE_RE.fullmatch(str(body.get("etf_code", ""))) else []
    codes = list(dict.fromkeys(ANY_CODE_RE.findall(question) + explicit))[:4]
    sections: list[dict] = []
    coverage = {"database": "data/etf_catcher.sqlite3", "window": window, "etfs": [], "groups": [], "indices": []}
    with sqlite3.connect(f"file:{DATABASE.as_posix()}?mode=ro", uri=True, timeout=8) as connection:
        connection.row_factory = sqlite3.Row
        masters = [dict(row) for row in connection.execute(
            "SELECT etf_code,etf_name,exchange,asset_class,category_l1,category_l2,tracking_index_code,tracking_index_name "
            "FROM etf_master WHERE enabled=1"
        )]
        for row in masters:
            if row.get("etf_name") and row["etf_name"] in question and row["etf_code"] not in codes:
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
                "FROM etf_daily WHERE etf_code=? ORDER BY trade_date DESC LIMIT ?", (code, window)
            )][::-1]
            sections.append({"type": "ETF历史", "meta": meta, "rows": rows})
            coverage["etfs"].append({"code": code, "name": meta["etf_name"], "start": rows[0]["trade_date"] if rows else None, "end": rows[-1]["trade_date"] if rows else None, "rows": len(rows)})
        overall = [dict(row) for row in connection.execute(
            "SELECT trade_date,SUM(net_flow) AS net_flow,SUM(amount) AS amount,COUNT(*) AS etf_rows "
            "FROM etf_daily WHERE trade_date IN (SELECT DISTINCT trade_date FROM etf_daily ORDER BY trade_date DESC LIMIT ?) "
            "GROUP BY trade_date ORDER BY trade_date", (window,)
        )]
        sections.append({"type": "全市场ETF历史", "rows": overall})
        table_names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "panel_group_daily" in table_names:
            names = [row[0] for row in connection.execute("SELECT DISTINCT group_name FROM panel_group_daily")]
            for name in matched_groups(question, names):
                rows = [dict(row) for row in connection.execute(
                    "SELECT * FROM panel_group_daily WHERE group_name=? ORDER BY trade_date DESC LIMIT ?", (name, window)
                )][::-1]
                sections.append({"type": "分类历史（与网页面板一致）", "name": name, "rows": rows})
                coverage["groups"].append({"name": name, "start": rows[0]["trade_date"] if rows else None, "end": rows[-1]["trade_date"] if rows else None, "rows": len(rows)})
        if "index_daily" in table_names:
            dates = [row[0] for row in connection.execute("SELECT DISTINCT date FROM index_daily ORDER BY date DESC LIMIT ?", (window,))]
            if dates:
                placeholders = ",".join("?" for _ in dates)
                indices = [dict(row) for row in connection.execute(
                    f"SELECT date,index_code,index_name,close,change_pct,normalized,source FROM index_daily WHERE date IN ({placeholders}) ORDER BY date,index_code", dates
                )]
                sections.append({"type": "全球指数历史", "rows": indices})
                coverage["indices"] = sorted({row["index_code"] for row in indices})
        if "macro_payload" in table_names:
            row = connection.execute("SELECT payload_json FROM macro_payload WHERE id=1").fetchone()
            if row:
                macro = json.loads(row[0])
                sections.append({"type": "宏观监控", "data": macro})
                coverage["macro_as_of"] = macro.get("target_date")
    encoded = json.dumps(sections, ensure_ascii=False, separators=(",", ":"))
    return encoded[:100_000], coverage


def run_node(script: str, arguments: list[str], timeout: int) -> dict:
    process = subprocess.run(["node", str(ROOT / "backend" / script), *arguments], capture_output=True, text=True, encoding="utf-8", timeout=timeout, check=True, env=os.environ.copy())
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
            skill = ifind_skill_dir() / "call-node.js"
            payload = {"status": "ready" if dates["rows"] else "setup_required", "database": DATABASE.exists(), **dates, "data_policy": "latest_previous_complete_trading_day", "data_policy_zh": "最新上一个完整交易日", "schedule_not_before": "08:30", "ifind_skill": skill.exists(), "deepseek": bool(model_setting("DEEPSEEK_API_KEY")), "last_update": load_json(ROOT / "runtime" / "update_status.json", {})}
            return self.send_json(payload)
        if parsed.path == "/api/ai/status":
            return self.send_json({"configured": bool(model_setting("DEEPSEEK_API_KEY")), "model": model_setting("DEEPSEEK_MODEL", "deepseek-chat"), "local_database": DATABASE.exists(), "online_search": (ifind_skill_dir() / "call-node.js").exists(), "default_history_days": 60})
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
            result = run_node("ifind_detail.js", [code], 75)
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
