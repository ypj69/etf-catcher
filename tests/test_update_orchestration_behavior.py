from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def powershell() -> str:
    executable = shutil.which("powershell.exe") or shutil.which("pwsh")
    assert executable, "ETF Catcher public build requires Windows PowerShell"
    return executable


def make_fixture(tmp_path: Path) -> Path:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (tmp_path / "data" / "web").mkdir(parents=True)
    (tmp_path / "runtime").mkdir()
    shutil.copy2(ROOT / "scripts" / "update_public.ps1", scripts / "update_public.ps1")
    (scripts / "plan_missing_sessions.py").write_text(
        "import json\nprint(json.dumps({'status':'pass','published_through':'2026-08-19',"
        "'dates':['2026-08-20','2026-08-21','2026-08-24']}))\n",
        encoding="utf-8",
    )
    (scripts / "update_one_day.ps1").write_text(
        "param([string]$Python,[string]$Database,[string]$TargetDate,[switch]$Resume)\n"
        "$TargetDate | Add-Content -LiteralPath (Join-Path (Split-Path -Parent $PSScriptRoot) 'runtime\\calls.txt')\n"
        "if($env:ETF_CATCHER_TEST_FAIL_DATE -eq $TargetDate){throw \"simulated failure $TargetDate\"}\n",
        encoding="utf-8",
    )
    return scripts / "update_public.ps1"


def run_fixture(script: Path, fail_date: str = "", target_date: str = "") -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["ETF_CATCHER_TEST_FAIL_DATE"] = fail_date
    command = [
        powershell(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-Python",
        sys.executable,
        "-Database",
        str(script.parents[1] / "data" / "test.sqlite3"),
    ]
    if target_date:
        command.extend(["-TargetDate", target_date])
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
    )


def test_batch_stops_on_failed_day_and_releases_lock(tmp_path: Path) -> None:
    script = make_fixture(tmp_path)
    result = run_fixture(script, "2026-08-21")
    assert result.returncode != 0
    runtime = tmp_path / "runtime"
    assert (runtime / "calls.txt").read_text(encoding="utf-8").splitlines() == ["2026-08-20", "2026-08-21"]
    status = json.loads((runtime / "update_status.json").read_text(encoding="utf-8-sig"))
    assert status["status"] == "failed"
    assert status["target_date"] == "2026-08-21"
    assert status["completed_count"] == 1
    assert status["total_count"] == 3
    assert not (runtime / "update.lock.json").exists()


def test_batch_runs_all_planned_days_in_order(tmp_path: Path) -> None:
    script = make_fixture(tmp_path)
    result = run_fixture(script)
    assert result.returncode == 0, result.stderr
    runtime = tmp_path / "runtime"
    assert (runtime / "calls.txt").read_text(encoding="utf-8").splitlines() == [
        "2026-08-20",
        "2026-08-21",
        "2026-08-24",
    ]
    status = json.loads((runtime / "update_status.json").read_text(encoding="utf-8-sig"))
    assert status["status"] == "pass"
    assert status["target_date"] == "2026-08-24"
    assert status["completed_count"] == 3
    assert status["total_count"] == 3
    assert not (runtime / "update.lock.json").exists()


def test_no_missing_sessions_is_a_successful_noop(tmp_path: Path) -> None:
    script = make_fixture(tmp_path)
    (script.parent / "plan_missing_sessions.py").write_text(
        "import json\nprint(json.dumps({'status':'pass','published_through':'2026-08-24','dates':[]}))\n",
        encoding="utf-8",
    )
    result = run_fixture(script)
    assert result.returncode == 0, result.stderr
    runtime = tmp_path / "runtime"
    assert not (runtime / "calls.txt").exists()
    status = json.loads((runtime / "update_status.json").read_text(encoding="utf-8-sig"))
    assert status["status"] == "pass"
    assert status["target_date"] == "2026-08-24"
    assert status["total_count"] == 0
    assert not (runtime / "update.lock.json").exists()


def test_explicit_target_keeps_single_day_diagnostic_mode(tmp_path: Path) -> None:
    script = make_fixture(tmp_path)
    result = run_fixture(script, target_date="2026-08-20")
    assert result.returncode == 0, result.stderr
    calls = (tmp_path / "runtime" / "calls.txt").read_text(encoding="utf-8").splitlines()
    assert calls == ["2026-08-20"]
