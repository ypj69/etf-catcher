param([string]$DailyTime='')
$ErrorActionPreference='Stop'
$Root=Split-Path -Parent $PSScriptRoot
$ConfigPath=Join-Path $Root 'config\app.local.json'
$Config=if(Test-Path -LiteralPath $ConfigPath){Get-Content -LiteralPath $ConfigPath -Raw|ConvertFrom-Json}else{Get-Content -LiteralPath (Join-Path $Root 'config\app.example.json') -Raw|ConvertFrom-Json}
if(-not $DailyTime){$DailyTime=[string]$Config.daily_time}
$ParsedTime=[datetime]::MinValue
if(-not [datetime]::TryParseExact($DailyTime,'HH:mm',$null,[Globalization.DateTimeStyles]::None,[ref]$ParsedTime)){throw 'DailyTime must use HH:mm format.'}
if($ParsedTime.TimeOfDay-lt [timespan]::FromHours(8.5)){throw 'DailyTime cannot be earlier than 08:30 because prior-trading-day iFinD data is not complete before then.'}
$PowerShell=(Get-Command powershell.exe).Source
$User=[Security.Principal.WindowsIdentity]::GetCurrent().Name
$Principal=New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
$Daily=New-ScheduledTaskAction -Execute $PowerShell -WorkingDirectory $Root -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "'+(Join-Path $Root 'update.ps1')+'"')
$Web=New-ScheduledTaskAction -Execute $PowerShell -WorkingDirectory $Root -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "'+(Join-Path $Root 'start.ps1')+'" -Background')
$Settings=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'ETF Catcher Daily Update' -Action $Daily -Trigger (New-ScheduledTaskTrigger -Daily -At $ParsedTime) -Settings $Settings -Principal $Principal -Force|Out-Null
Register-ScheduledTask -TaskName 'ETF Catcher Web Service' -Action $Web -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $User) -Settings $Settings -Principal $Principal -Force|Out-Null
Write-Host "Registered the local daily update at $DailyTime and the logon startup task." -ForegroundColor Green
