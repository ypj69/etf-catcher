from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_market_jobs_only_request_four_fields(tmp_path: Path, monkeypatch) -> None:
    module = load_module(ROOT / "scripts" / "prepare_ifind_jobs_t1.py", "prepare_jobs")
    output = tmp_path / "jobs.json"
    monkeypatch.setattr("sys.argv", ["prepare", "--date", "2026-08-19", "--output", str(output), "--limit", "5"])
    module.main()
    query = json.loads(output.read_text(encoding="utf-8"))[0]["query"]
    assert all(field in query for field in ("基金份额", "基金规模", "收盘价", "成交额"))
    assert all(field not in query for field in ("开盘价", "最高价", "最低价", "涨跌幅", "成交量"))


def test_public_server_never_reads_plaintext_secret_file() -> None:
    text = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend" / "assets" / "app_v2.js").read_text(encoding="utf-8")
    assert "secrets.local.json" not in text
    assert "secrets.local.json" not in frontend
    assert 'model_setting("DEEPSEEK_API_KEY")' in text


def test_repository_has_no_private_absolute_paths() -> None:
    forbidden = re.compile(r"(?:D:\\\\Tools|D:\\\\资金流|C:\\\\Users\\\\YUAN|ROOT\.parent\s*/\s*[\"']Data)")
    failures = []
    for base in (ROOT / "backend", ROOT / "scripts", ROOT / "tools"):
        for path in base.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".py", ".js", ".ps1"}:
                if forbidden.search(path.read_text(encoding="utf-8", errors="ignore")):
                    failures.append(str(path.relative_to(ROOT)))
    assert not failures


def test_single_server_entry_and_public_baseline() -> None:
    assert sorted(path.name for path in (ROOT / "backend").glob("server*.py")) == ["server.py"]
    baseline = json.loads((ROOT / "config" / "production_baseline.json").read_text(encoding="utf-8"))
    assert baseline["server_entry"] == "backend/server.py"
    assert baseline["baseline_id"] == "etf-catcher-public-1.0.1"


def test_local_skill_and_schedule_floor() -> None:
    assert (ROOT / "SKILL.md").is_file()
    config = json.loads((ROOT / "config" / "app.example.json").read_text(encoding="utf-8"))
    assert config["daily_time"] == "08:30"
    register = (ROOT / "scripts" / "register_tasks.ps1").read_text(encoding="utf-8")
    configure = (ROOT / "configure.ps1").read_text(encoding="utf-8")
    assert "cannot be earlier than 08:30" in register
    assert "cannot be earlier than 08:30" in configure


def test_previous_complete_trading_day_is_disclosed() -> None:
    server = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend" / "assets" / "final_tweaks.js").read_text(encoding="utf-8")
    assert "latest_previous_complete_trading_day" in server
    assert "最新上一个完整交易日" in frontend


def test_target_date_uses_ifind_sessions_and_fails_closed() -> None:
    resolver = (ROOT / "scripts" / "resolve_target_market_date.py").read_text(encoding="utf-8")
    daily_updater = (ROOT / "scripts" / "update_one_day.ps1").read_text(encoding="utf-8")
    assert "latest_ifind_session" in resolver
    assert "休市日不要返回" in resolver
    assert "stopped to avoid treating a holiday as a trading day" in resolver
    assert "TargetDate must be earlier than today" in daily_updater
