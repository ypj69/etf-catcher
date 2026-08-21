from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path


def load_call(skill_dir: Path):
    path = skill_dir / "call.py"
    if not path.is_file():
        raise FileNotFoundError(f"iFinD Python caller not found: {path}")
    spec = importlib.util.spec_from_file_location("etf_catcher_ifind_call", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load the iFinD Python caller")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.call


def result_text(result: dict) -> str:
    content = (((result.get("data") or {}).get("result") or {}).get("content") or [])
    return "\n".join(str(item.get("text") or "") for item in content if isinstance(item, dict))


def main() -> None:
    code = re.sub(r"\D", "", sys.argv[1] if len(sys.argv) > 1 else "")
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError("ETF code is invalid")
    suffix = "SH" if code.startswith("5") else "SZ"
    symbol = f"{code}.{suffix}"
    skill_dir = Path(os.environ.get("IFIND_SKILL_DIR", Path.home() / ".codex" / "skills" / "ifind-finance-data"))
    call = load_call(skill_dir)
    profile = call("fund", "get_fund_profile", {"query": f"查询{symbol}的基金简称、全称、成立日、上市日、基金管理人、基金经理、投资类型、跟踪指数名称、跟踪指数代码、管理费率和托管费率"})
    portfolio = call("fund", "get_fund_portfolio", {"query": f"查询{symbol}最新一期前十大重仓股，列出证券代码、证券名称、持仓市值、持仓数量、占基金资产净值比例和报告期"})
    quotes = call("fund", "fund_highfreq_quotes", {"symbols": symbol, "indicators": "最新价,今开,最高,最低,涨跌幅,成交额,成交量,IOPV净值估值,折溢价", "data_mode": "real_time", "interval": 1})
    payload = json.dumps({"profile": result_text(profile), "portfolio": result_text(portfolio), "quotes": result_text(quotes)}, ensure_ascii=False)
    sys.stdout.buffer.write(payload.encode("utf-8"))


if __name__ == "__main__":
    main()
