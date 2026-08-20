param(
  [Parameter(Mandatory=$true)][string]$Python,
  [Parameter(Mandatory=$true)][string]$Database,
  [string]$TargetDate='',
  [switch]$Resume
)
$ErrorActionPreference='Stop'
$Root=Split-Path -Parent $PSScriptRoot
$Runtime=Join-Path $Root 'runtime'
$Logs=Join-Path $Root 'logs'
New-Item -ItemType Directory -Path $Runtime,$Logs,(Join-Path $Root 'data\web') -Force|Out-Null
$Lock=Join-Path $Runtime 'update.lock.json'
$Status=Join-Path $Runtime 'update_status.json'
$PlanPath=Join-Path $Runtime 'missing_sessions_plan.json'
$CurrentDate=$null
$Completed=0
$Dates=@()
function Write-BatchStatus($State,$Stage,$Detail){
  [ordered]@{
    status=$State;stage=$Stage;detail=$Detail;target_date=if($CurrentDate){$CurrentDate}elseif($TargetDate){$TargetDate}else{$null}
    completed_count=$Completed;total_count=$Dates.Count;batch_dates=$Dates;pid=$PID;updated_at=(Get-Date).ToString('o')
  }|ConvertTo-Json -Depth 4|Set-Content -LiteralPath $Status -Encoding utf8
}
if(Test-Path -LiteralPath $Lock){
  try{$Owner=Get-Content -LiteralPath $Lock -Raw|ConvertFrom-Json;$Active=Get-Process -Id ([int]$Owner.pid)-ErrorAction SilentlyContinue}catch{$Active=$null}
  if($Active){throw "Update process $($Owner.pid) is already running."}
  Move-Item -LiteralPath $Lock -Destination "$Lock.stale.$(Get-Date -Format yyyyMMddHHmmss)"
}
[ordered]@{pid=$PID;requested_target=$TargetDate;started_at=(Get-Date).ToString('o')}|ConvertTo-Json|Set-Content -LiteralPath $Lock -Encoding utf8
try{
  if($TargetDate){
    $Dates=@($TargetDate)
  }else{
    Write-BatchStatus 'running' 'plan' 'finding every unpublished iFinD trading session'
    $PlanJson=& $Python (Join-Path $PSScriptRoot 'plan_missing_sessions.py') --database $Database --meta (Join-Path $Root 'data\web\meta.json')
    if($LASTEXITCODE-ne 0){throw "missing-session planning failed with exit code $LASTEXITCODE"}
    $Plan=$PlanJson|ConvertFrom-Json
    $Plan|ConvertTo-Json -Depth 5|Set-Content -LiteralPath $PlanPath -Encoding utf8
    $Dates=@($Plan.dates)
    if($Dates.Count-eq 0){
      $CurrentDate=[string]$Plan.published_through
      Write-BatchStatus 'pass' 'complete' 'no unpublished trading sessions; local data is already current'
      return
    }
  }
  for($Index=0;$Index-lt$Dates.Count;$Index++){
    $CurrentDate=[string]$Dates[$Index]
    Write-BatchStatus 'running' 'backfill' "publishing trading session $($Index+1) of $($Dates.Count)"
    & (Join-Path $PSScriptRoot 'update_one_day.ps1') -Python $Python -Database $Database -TargetDate $CurrentDate -Resume:$Resume
    $Completed=$Index+1
  }
  Write-BatchStatus 'pass' 'complete' 'all missing trading sessions published in chronological order'
}catch{
  Write-BatchStatus 'failed' 'error' $_.Exception.Message
  throw
}finally{
  if(Test-Path -LiteralPath $Lock){Remove-Item -LiteralPath $Lock -Force}
}
