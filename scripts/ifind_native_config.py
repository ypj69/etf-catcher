"""Optional per-user native API credentials; no plaintext configuration files."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CREDENTIAL_PATH = ROOT / "config" / "ifind-native.local.dpapi"


def load_credentials() -> tuple[str, str]:
    username = os.environ.get("IFIND_API_USERNAME", "")
    password = os.environ.get("IFIND_API_PASSWORD", "")
    if username or password:
        if not username or not password:
            raise RuntimeError("Set both IFIND_API_USERNAME and IFIND_API_PASSWORD, or remove both to use DPAPI.")
        return username, password
    if not CREDENTIAL_PATH.is_file():
        raise RuntimeError("Native API fallback is not configured. Run configure-ifind.ps1; see README.")
    # Plaintext stays in captured process memory, never command arguments or logs.
    script = r'''
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1') -ErrorAction Stop
[Console]::InputEncoding=[System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
$path=[Console]::In.ReadToEnd().Trim()
$secure=Get-Content -Raw -LiteralPath $path | ConvertTo-SecureString
$ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try { [Console]::Write([Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
'''
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            input=str(CREDENTIAL_PATH), capture_output=True, text=True,
            encoding="utf-8", timeout=30, check=False,
        )
        if result.returncode:
            raise ValueError("DPAPI failure")
        payload = json.loads(result.stdout.lstrip("\ufeff"))
        username, password = payload["username"], payload["password"]
        if not isinstance(username, str) or not isinstance(password, str) or not username or not password:
            raise ValueError("Empty credentials")
        return username, password
    except Exception:
        raise RuntimeError("Cannot decrypt native API credentials. Run configure-ifind.ps1 under the Windows user running updates.") from None
