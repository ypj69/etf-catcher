param([string]$TargetDate='',[switch]$Resume)
$ErrorActionPreference='Stop'
$Root=Split-Path -Parent $MyInvocation.MyCommand.Path
$Python=Join-Path $Root '.venv\Scripts\python.exe'
$Database=Join-Path $Root 'data\etf_catcher.sqlite3'
if(-not (Test-Path -LiteralPath $Python)){throw 'Run setup.ps1 before updating.'}
if(-not (Test-Path -LiteralPath $Database)){throw 'The seed database is not installed.'}
$ConfigPath=Join-Path $Root 'config\app.local.json'
if(Test-Path -LiteralPath $ConfigPath){$Config=Get-Content -LiteralPath $ConfigPath -Raw|ConvertFrom-Json;if($Config.ifind_skill_dir){$env:IFIND_SKILL_DIR=[string]$Config.ifind_skill_dir}}
& (Join-Path $Root 'scripts\update_public.ps1') -Python $Python -Database $Database -TargetDate $TargetDate -Resume:$Resume
$UpdateExit=$LASTEXITCODE
if($UpdateExit-ne 0){exit $UpdateExit}
if($Config -and [bool]$Config.notifications_enabled){
  $NotifyEntry=Join-Path $Root 'extensions\cc-connect\notify.ps1'
  if(Test-Path -LiteralPath $NotifyEntry){
    try{& $NotifyEntry}catch{Write-Warning "Web update succeeded, but optional notification failed: $($_.Exception.Message)"}
  }else{
    Write-Warning 'Web update succeeded. Notifications are enabled, but extensions\cc-connect\notify.ps1 is not configured.'
  }
}
exit 0
