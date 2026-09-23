from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from ifind_native_config import load_credentials


ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = ROOT / "runtime" / "ifind_collection_route_status.json"
QUOTA_TOKENS = ("用户使用工具已超限", "额度已用完", "额度不足", "额度耗尽", "额度已耗尽", "quota exhausted", "insufficient quota", "IFIND_QUOTA_EXHAUSTED")


def is_quota_exhausted(output: object) -> bool:
    text = str(output or "").lower()
    return any(token.lower() in text for token in QUOTA_TOKENS)


def write_status(status: str, route: str, jobs: str, output: str, **detail: object) -> None:
    payload = {
        "status": status,
        "route": route,
        "jobs": str(Path(jobs).resolve()),
        "output": str(Path(output).resolve()),
        "updated_at": datetime.now().astimezone().isoformat(),
        **detail,
    }
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def emit_captured(result: subprocess.CompletedProcess[str]) -> None:
    # PowerShell 5 promotes native stderr to a terminating error when the
    # production parent uses ErrorActionPreference=Stop. Emit captured child
    # diagnostics through stdout; the child return code still controls failure.
    for value in (result.stdout, result.stderr):
        if value and value.strip():
            print(value.rstrip())


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Use iFinD MCP first and fall back to the native Python API only on quota exhaustion")
    parser.add_argument("--jobs", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--attempts", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=1)
    args = parser.parse_args()

    node_result = run(
        [
            "node",
            str(ROOT / "scripts" / "collect_ifind_incremental.js"),
            "--jobs",
            args.jobs,
            "--output",
            args.output,
            "--tool",
            "get_fund_ownership",
            "--concurrency",
            str(max(1, min(2, args.concurrency))),
            "--attempts",
            str(max(1, min(5, args.attempts))),
        ]
    )
    combined = "\n".join(value for value in (node_result.stdout, node_result.stderr) if value)
    if node_result.returncode == 0:
        emit_captured(node_result)
        write_status("pass", "ifind_mcp", args.jobs, args.output, mcp_exit_code=0, fallback_used=False)
        return

    if not is_quota_exhausted(combined):
        emit_captured(node_result)
        write_status(
            "fail",
            "ifind_mcp",
            args.jobs,
            args.output,
            mcp_exit_code=node_result.returncode,
            fallback_used=False,
            reason="non_quota_mcp_failure",
        )
        raise SystemExit(node_result.returncode or 1)

    print(json.dumps({"status": "fallback", "from": "iFinD_MCP", "to": "iFinD_Python_API", "reason": "用户使用工具已超限"}, ensure_ascii=False))
    try:
        load_credentials()
    except RuntimeError as exc:
        print(str(exc))  # Helper emits only fixed, credential-free guidance.
        write_status("fail", "ifind_mcp", args.jobs, args.output,
                     fallback_used=False, reason="native_credentials_unavailable",
                     mcp_exit_code=node_result.returncode)
        raise SystemExit(1)
    write_status(
        "running",
        "ifind_python_api",
        args.jobs,
        args.output,
        mcp_exit_code=node_result.returncode,
        fallback_used=True,
        reason="mcp_quota_exhausted",
    )
    python_result = run(
        [
            sys.executable,
            str(ROOT / "scripts" / "collect_ifind_python_api.py"),
            "--jobs",
            args.jobs,
            "--output",
            args.output,
            "--attempts",
            str(max(1, min(5, args.attempts))),
        ]
    )
    emit_captured(python_result)
    status = "pass" if python_result.returncode == 0 else "fail"
    write_status(
        status,
        "ifind_python_api",
        args.jobs,
        args.output,
        mcp_exit_code=node_result.returncode,
        python_exit_code=python_result.returncode,
        fallback_used=True,
        reason="mcp_quota_exhausted",
    )
    raise SystemExit(python_result.returncode)


if __name__ == "__main__":
    main()
