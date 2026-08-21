from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_detail_uses_python_skill_when_node_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    skill = tmp_path / "ifind-skill"
    skill.mkdir()
    (skill / "call.py").write_text(
        "def call(server, tool, params):\n"
        "    return {'data': {'result': {'content': [{'text': tool}]}}}\n",
        encoding="utf-8",
    )
    server = load_module(ROOT / "backend" / "server.py", "public_server_runtime")
    monkeypatch.setenv("IFIND_SKILL_DIR", str(skill))
    monkeypatch.setattr(server.shutil, "which", lambda name: None)
    result = server.run_ifind_detail("510300", timeout=15)
    assert result == {
        "profile": "get_fund_profile",
        "portfolio": "get_fund_portfolio",
        "quotes": "fund_highfreq_quotes",
    }


def test_public_legacy_market_parser_applies_compound_units() -> None:
    parser = load_module(ROOT / "scripts" / "ingest_ifind_t1.py", "public_legacy_parser")
    assert parser.number_with_unit("173.3852万", "万元") == 17_338_520_000.0


def test_skill_health_accepts_python_caller(tmp_path: Path, monkeypatch) -> None:
    skill = tmp_path / "ifind-skill"
    skill.mkdir()
    (skill / "call.py").write_text("", encoding="utf-8")
    server = load_module(ROOT / "backend" / "server.py", "public_server_health")
    monkeypatch.setenv("IFIND_SKILL_DIR", str(skill))
    assert server.ifind_skill_ready()
def test_python_detail_writes_utf8_bytes() -> None:
    text = (ROOT / "backend" / "ifind_detail.py").read_text(encoding="utf-8")
    assert 'sys.stdout.buffer.write(payload.encode("utf-8"))' in text
