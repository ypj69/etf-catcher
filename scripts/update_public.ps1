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
$FailureState=Join-Path $Runtime 'backfill_failures.json'
$UniverseLog=Join-Path $Logs "etf_universe_$((Get-Date).ToString('yyyyMMdd')).log"
$UpdateRunId=(Get-Date).ToString('yyyyMMddTHHmmssfffffff')
$CurrentDate=$null
$Completed=0
$Dates=@()
$GapDates=@()
$PublishTarget=$null
$WindowStart=$null
$PublishableDates=@()
function Write-BatchStatus($State,$Stage,$Detail){
  [ordered]@{
    status=$State;stage=$Stage;detail=$Detail
    target_date=if($CurrentDate){$CurrentDate}elseif($PublishTarget){$PublishTarget}elseif($TargetDate){$TargetDate}else{$null}
    completed_count=$Completed;total_count=$Dates.Count;batch_dates=$Dates;pid=$PID;updated_at=(Get-Date).ToString('o')
  }|ConvertTo-Json -Depth 4|Set-Content -LiteralPath $Status -Encoding utf8
}
if(Test-Path -LiteralPath $Lock){
  try{$Owner=Get-Content -LiteralPath $Lock -Raw|ConvertFrom-Json;$Active=Get-Process -Id ([int]$Owner.pid)-ErrorAction SilentlyContinue}catch{$Active=$null}
  if($Active){throw "Update process $($Owner.pid) is already running."}
  Move-Item -LiteralPath $Lock -Destination "$Lock.stale.$(Get-Date -Format yyyyMMddHHmmss)"
}
[ordered]@{pid=$PID;requested_target=$TargetDate;run_id=$UpdateRunId;started_at=(Get-Date).ToString('o')}|ConvertTo-Json|Set-Content -LiteralPath $Lock -Encoding utf8
try{
  Write-BatchStatus 'running' 'universe' 'checking whether the weekly ETF universe maintenance is due'
  $UniverseScript=Join-Path $PSScriptRoot 'maintain_etf_universe.py'
  if(Test-Path -LiteralPath $UniverseScript){
    & $Python $UniverseScript --database $Database --nonblocking *>> $UniverseLog
    if($LASTEXITCODE-ne 0){Write-Warning "ETF universe maintenance returned exit code $LASTEXITCODE; the last successful universe remains active."}
  }else{
    Write-Warning 'ETF universe maintenance script is unavailable; the last successful universe remains active.'
  }
  if($TargetDate){
    $Dates=@($TargetDate)
    $GapDates=@($TargetDate)
    $PublishTarget=$TargetDate
    $WindowStart=$TargetDate
  }else{
    Write-BatchStatus 'running' 'plan' 'finding incomplete sessions after the last successful web publication'
    $PlanJson=& $Python (Join-Path $PSScriptRoot 'plan_missing_sessions.py') --database $Database --meta (Join-Path $Root 'data\web\meta.json') --state $FailureState
    if($LASTEXITCODE-ne 0){throw "missing-session planning failed with exit code $LASTEXITCODE"}
    $Plan=$PlanJson|ConvertFrom-Json
    $Plan|ConvertTo-Json -Depth 6|Set-Content -LiteralPath $PlanPath -Encoding utf8
    $Dates=@($Plan.dates)
    $GapDates=@($Plan.gap_dates)
    $PublishTarget=[string]$Plan.target_date
    $WindowStart=[string]$Plan.window_start
    $PublishableDates=@($Plan.ready_dates)
    if(-not $Plan.publication_required){
      $CurrentDate=[string]$Plan.published_through
      Write-BatchStatus 'pass' 'complete' 'no sessions exist after the last successful web publication'
      return
    }
  }

  for($Index=0;$Index-lt$Dates.Count;$Index++){
    $CurrentDate=[string]$Dates[$Index]
    Write-BatchStatus 'running' 'backfill' "collecting missing session $($Index+1) of $($Dates.Count)"
    try{
      & (Join-Path $PSScriptRoot 'update_one_day.ps1') -Python $Python -Database $Database -TargetDate $CurrentDate -Resume:$Resume -CollectOnly
      & $Python (Join-Path $PSScriptRoot 'backfill_control.py') record-success --state $FailureState --date $CurrentDate | Out-Null
      if($LASTEXITCODE-ne 0){throw "backfill state update failed for $CurrentDate"}
      $PublishableDates += $CurrentDate
    }catch{
      $FailureJson=& $Python (Join-Path $PSScriptRoot 'backfill_control.py') record-failure --state $FailureState --date $CurrentDate --run-id $UpdateRunId --error $_.Exception.Message
      if($LASTEXITCODE-ne 0){throw}
      $Failure=$FailureJson|ConvertFrom-Json
      if($Failure.quarantined){
        Write-Warning "Source gap $CurrentDate was isolated after $($Failure.failed_runs) failed runs; later sessions will continue."
      }else{
        throw
      }
    }
    $Completed=$Index+1
  }

  $PublishableDates=@($PublishableDates|Sort-Object -Unique)
  if($PublishableDates.Count-eq 0){
    & $Python (Join-Path $PSScriptRoot 'enrich_web_meta.py')
    if($LASTEXITCODE-ne 0){throw 'source-gap metadata update failed'}
    $CurrentDate=if($GapDates.Count){[string]$GapDates[-1]}else{$PublishTarget}
    Write-BatchStatus 'pass' 'degraded' 'no complete new session is publishable; the previous web remains intact and the source gap is disclosed'
    return
  }
  $PublishTarget=[string]$PublishableDates[-1]
  $CurrentDate=$PublishTarget
  Write-BatchStatus 'running' 'publish' 'all available gap sessions are stored; building the web once'
  & (Join-Path $PSScriptRoot 'publish_web.ps1') -Python $Python -Database $Database -TargetDate $PublishTarget -StartDate $WindowStart
  Write-BatchStatus 'pass' 'complete' 'gap recovery finished and the web was published once'
}catch{
  Write-BatchStatus 'failed' 'error' $_.Exception.Message
  throw
}finally{
  if(Test-Path -LiteralPath $Lock){Remove-Item -LiteralPath $Lock -Force}
}
