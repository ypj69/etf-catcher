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
    (scripts / 'ensure_macro_cache.py').write_text("from pathlib import Path\nPath(__file__).parents[1].joinpath('runtime','macro_checked.txt').write_text('checked')\n", encoding='utf-8')
    (scripts / "plan_missing_sessions.py").write_text(
        "import json\nprint(json.dumps({'status':'pending','published_through':'2026-08-19',"
        "'window_start':'2026-08-20','target_date':'2026-08-24','publication_required':True,"
        "'gap_dates':['2026-08-20','2026-08-21','2026-08-24'],"
        "'dates':['2026-08-20','2026-08-21','2026-08-24']}))\n",
        encoding="utf-8",
    )
    (scripts / "update_one_day.ps1").write_text(
        "param([string]$Python,[string]$Database,[string]$TargetDate,[switch]$Resume,[switch]$CollectOnly)\n"
        "$TargetDate | Add-Content -LiteralPath (Join-Path (Split-Path -Parent $PSScriptRoot) 'runtime\\calls.txt')\n"
        "if($env:ETF_CATCHER_TEST_FAIL_DATE -eq $TargetDate){throw \"simulated failure $TargetDate\"}\n",
        encoding="utf-8",
    )
    (scripts / "backfill_control.py").write_text(
        "import json,os,sys\n"
        "command=sys.argv[1]\n"
        "quarantined=os.getenv('ETF_CATCHER_TEST_QUARANTINE')=='1'\n"
        "if command=='record-failure': print(json.dumps({'failed_runs':3 if quarantined else 1,'quarantined':quarantined}))\n"
        "else: print(json.dumps({'status':'resolved'}))\n",
        encoding="utf-8",
    )
    (scripts / "publish_web.ps1").write_text(
        "param([string]$Python,[string]$Database,[string]$TargetDate,[string]$StartDate)\n"
        "$TargetDate | Add-Content -LiteralPath (Join-Path (Split-Path -Parent $PSScriptRoot) 'runtime\\published.txt')\n",
        encoding="utf-8",
    )
    (scripts / "enrich_web_meta.py").write_text(
        "from pathlib import Path\n"
        "Path(__file__).parents[1].joinpath('runtime', 'metadata.txt').write_text('source gap disclosed', encoding='utf-8')\n",
        encoding="utf-8",
    )
    return scripts / "update_public.ps1"


def run_fixture(script: Path, fail_date: str = "", target_date: str = "", quarantine: bool = False) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["ETF_CATCHER_TEST_FAIL_DATE"] = fail_date
    environment["ETF_CATCHER_TEST_QUARANTINE"] = "1" if quarantine else "0"
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


def test_batch_stops_on_unresolved_day_and_preserves_old_web(tmp_path: Path) -> None:
    script = make_fixture(tmp_path)
    result = run_fixture(script, "2026-08-21")
    assert result.returncode != 0
    runtime = tmp_path / "runtime"
    assert (runtime / "calls.txt").read_text(encoding="utf-8").splitlines() == ["2026-08-20", "2026-08-21"]
    assert not (runtime / "published.txt").exists()
    status = json.loads((runtime / "update_status.json").read_text(encoding="utf-8-sig"))
    assert status["status"] == "failed"
    assert status["target_date"] == "2026-08-21"
    assert not (runtime / "update.lock.json").exists()


def test_batch_collects_all_days_then_publishes_once(tmp_path: Path) -> None:
    script = make_fixture(tmp_path)
    result = run_fixture(script)
    assert result.returncode == 0, result.stderr
    runtime = tmp_path / "runtime"
    assert (runtime / "calls.txt").read_text(encoding="utf-8").splitlines() == [
        "2026-08-20",
        "2026-08-21",
        "2026-08-24",
    ]
    assert (runtime / "published.txt").read_text(encoding="utf-8").splitlines() == ["2026-08-24"]
    status = json.loads((runtime / "update_status.json").read_text(encoding="utf-8-sig"))
    assert status["status"] == "pass"
    assert status["target_date"] == "2026-08-24"
    assert not (runtime / "update.lock.json").exists()


def test_no_gap_sessions_is_a_successful_noop(tmp_path: Path) -> None:
    script = make_fixture(tmp_path)
    (script.parent / "plan_missing_sessions.py").write_text(
        "import json\nprint(json.dumps({'status':'complete','published_through':'2026-08-24',"
        "'window_start':'2026-08-24','target_date':'2026-08-24',"
        "'publication_required':False,'gap_dates':[],'dates':[]}))\n",
        encoding="utf-8",
    )
    result = run_fixture(script)
    assert result.returncode == 0, result.stderr
    runtime = tmp_path / "runtime"
    assert not (runtime / "calls.txt").exists()
    assert (runtime / "macro_checked.txt").exists()
    assert not (runtime / "published.txt").exists()
    status = json.loads((runtime / "update_status.json").read_text(encoding="utf-8-sig"))
    assert status["status"] == "pass"
    assert status["target_date"] == "2026-08-24"
    assert not (runtime / "update.lock.json").exists()


def test_explicit_target_keeps_single_day_diagnostic_mode(tmp_path: Path) -> None:
    script = make_fixture(tmp_path)
    result = run_fixture(script, target_date="2026-08-20")
    assert result.returncode == 0, result.stderr
    runtime = tmp_path / "runtime"
    assert (runtime / "calls.txt").read_text(encoding="utf-8").splitlines() == ["2026-08-20"]
    assert (runtime / "published.txt").read_text(encoding="utf-8").splitlines() == ["2026-08-20"]

def test_quarantined_only_day_keeps_previous_web_and_discloses_gap(tmp_path: Path) -> None:
    script = make_fixture(tmp_path)
    result = run_fixture(script, "2026-08-20", target_date="2026-08-20", quarantine=True)
    assert result.returncode == 0, result.stderr
    runtime = tmp_path / "runtime"
    assert not (runtime / "published.txt").exists()
    assert (runtime / "metadata.txt").read_text(encoding="utf-8") == "source gap disclosed"
    status = json.loads((runtime / "update_status.json").read_text(encoding="utf-8-sig"))
    assert status["status"] == "pass"
    assert status["stage"] == "degraded"
