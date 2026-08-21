param([switch]$SkipDeepSeek,[switch]$EnableNotifications,[string]$DailyTime='08:30')
$ErrorActionPreference='Stop'
$Root=Split-Path -Parent $MyInvocation.MyCommand.Path
$ConfigDir=Join-Path $Root 'config'
$LocalConfig=Join-Path $ConfigDir 'app.local.json'
$Example=Get-Content -LiteralPath (Join-Path $ConfigDir 'app.example.json') -Raw|ConvertFrom-Json
$SkillDefault=Join-Path $HOME '.codex\skills\ifind-finance-data'
$SkillPath=if($env:IFIND_SKILL_DIR){$env:IFIND_SKILL_DIR}else{$SkillDefault}
$SkillReady=(Test-Path -LiteralPath (Join-Path $SkillPath 'call-node.js')) -or (Test-Path -LiteralPath (Join-Path $SkillPath 'call.py'))
$ParsedTime=[datetime]::MinValue
if(-not [datetime]::TryParseExact($DailyTime,'HH:mm',$null,[Globalization.DateTimeStyles]::None,[ref]$ParsedTime)){throw 'DailyTime must use HH:mm format.'}
if($ParsedTime.TimeOfDay-lt [timespan]::FromHours(8.5)){throw 'DailyTime cannot be earlier than 08:30 because prior-trading-day iFinD data is not complete before then.'}
$Config=[ordered]@{host=$Example.host;port=$Example.port;daily_time=$Example.daily_time;notifications_enabled=[bool]$EnableNotifications;ifind_skill_dir=if($SkillReady){$SkillPath}else{''}}
$Config.daily_time=$DailyTime
$Config|ConvertTo-Json|Set-Content -LiteralPath $LocalConfig -Encoding utf8
if(-not $SkipDeepSeek){
  $SecureKey=Read-Host 'Enter your DeepSeek API key (hidden), or cancel and rerun with -SkipDeepSeek' -AsSecureString
  $Encrypted=ConvertFrom-SecureString -SecureString $SecureKey
  $Encrypted|Set-Content -LiteralPath (Join-Path $ConfigDir 'secrets.local.dpapi') -Encoding ascii
}
if($SkillReady){Write-Host "iFinD Skill detected: $SkillPath" -ForegroundColor Green}else{Write-Warning 'iFinD Skill was not detected. Seed data remains available, but live detail and updates require the Skill.'}
Write-Host 'Local configuration completed. The key is protected with Windows DPAPI.' -ForegroundColor Green
Write-Host "Daily updates are configured for $DailyTime and always target the latest previous complete trading day." -ForegroundColor Green
