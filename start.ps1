param([switch]$Background)
$ErrorActionPreference='Stop'
$Root=Split-Path -Parent $MyInvocation.MyCommand.Path
$Python=Join-Path $Root '.venv\Scripts\python.exe'
if(-not (Test-Path -LiteralPath $Python)){throw 'The project environment is missing. Run setup.ps1 first.'}
$ConfigPath=Join-Path $Root 'config\app.local.json'
$Config=if(Test-Path -LiteralPath $ConfigPath){Get-Content -LiteralPath $ConfigPath -Raw|ConvertFrom-Json}else{Get-Content -LiteralPath (Join-Path $Root 'config\app.example.json') -Raw|ConvertFrom-Json}
if($Config.ifind_skill_dir){$env:IFIND_SKILL_DIR=[string]$Config.ifind_skill_dir}
$SecretPath=Join-Path $Root 'config\secrets.local.dpapi'
if(Test-Path -LiteralPath $SecretPath){
  $Secure=Get-Content -LiteralPath $SecretPath -Raw|ConvertTo-SecureString
  $Pointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
  try{$env:DEEPSEEK_API_KEY=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($Pointer)}finally{[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Pointer)}
}
$Args=@((Join-Path $Root 'backend\server.py'),'--host',[string]$Config.host,'--port',[string]$Config.port)
if($Background){
  New-Item -ItemType Directory -Path (Join-Path $Root 'logs'),(Join-Path $Root 'runtime') -Force|Out-Null
  $Process=Start-Process -FilePath $Python -ArgumentList $Args -WorkingDirectory $Root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $Root 'logs\web.out.log') -RedirectStandardError (Join-Path $Root 'logs\web.err.log') -PassThru
  [ordered]@{pid=$Process.Id;url="http://$($Config.host):$($Config.port)";started_at=(Get-Date).ToString('o')}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $Root 'runtime\web_server_status.json') -Encoding utf8
  Write-Host "ETF Catcher started in the background: http://$($Config.host):$($Config.port)"
}else{& $Python @Args}
$env:DEEPSEEK_API_KEY=$null
