param(
  [Parameter(Mandatory=$true)][string]$Python,
  [Parameter(Mandatory=$true)][string]$Database,
  [Parameter(Mandatory=$true)][string]$TargetDate,
  [switch]$Resume
)
$ErrorActionPreference='Stop'
$Root=Split-Path -Parent $PSScriptRoot
$Runtime=Join-Path $Root 'runtime'
$Logs=Join-Path $Root 'logs'
New-Item -ItemType Directory -Path $Runtime,$Logs,(Join-Path $Root 'data\raw\ifind'),(Join-Path $Root 'data\processed'),(Join-Path $Root 'data\web') -Force|Out-Null
$Node=Get-Command node -ErrorAction SilentlyContinue
if(-not $Node){throw 'Node.js is not installed or not in PATH.'}
$Skill=if($env:IFIND_SKILL_DIR){$env:IFIND_SKILL_DIR}else{Join-Path $HOME '.codex\skills\ifind-finance-data'}
if(-not (Test-Path -LiteralPath (Join-Path $Skill 'call-node.js'))){throw 'The current user has not installed the iFinD Skill.'}
$ParsedTarget=[datetime]::MinValue
if(-not [datetime]::TryParseExact($TargetDate,'yyyy-MM-dd',[Globalization.CultureInfo]::InvariantCulture,[Globalization.DateTimeStyles]::None,[ref]$ParsedTarget)){throw 'TargetDate must use YYYY-MM-DD.'}
if($ParsedTarget.Date -ge (Get-Date).Date){throw 'TargetDate must be earlier than today; current-day or future data cannot be published.'}
$RunId=$TargetDate.Replace('-','')
$Status=Join-Path $Runtime 'update_status.json'
$Log=Join-Path $Logs "update_$RunId.log"
function Write-Status($State,$Stage,$Detail){[ordered]@{status=$State;stage=$Stage;detail=$Detail;target_date=$TargetDate;pid=$PID;updated_at=(Get-Date).ToString('o')}|ConvertTo-Json|Set-Content -LiteralPath $Status -Encoding utf8}
function Assert-Step($Name){if($LASTEXITCODE-ne 0){throw "$Name failed with exit code $LASTEXITCODE"}}
try{
  Write-Status 'running' 'preflight' 'checking local database, Node and user iFinD skill'
  & $Python (Join-Path $PSScriptRoot 'restore_processed_seeds.py') --database $Database *>>$Log;Assert-Step 'restore processed seeds'
  $MetaPath=Join-Path $Root 'data\web\meta.json'
  $CanResume=$false
  if($Resume -and (Test-Path -LiteralPath $MetaPath)){$Meta=Get-Content -LiteralPath $MetaPath -Raw|ConvertFrom-Json;$CanResume=$Meta.market_latest-eq $TargetDate -and $Meta.flow_latest-eq $TargetDate}
  if(-not $CanResume){
    Write-Status 'running' 'market' 'collecting four dashboard market fields'
    $Jobs=Join-Path $Root "data\raw\ifind\jobs_market_$RunId.json";$Results=Join-Path $Root "data\raw\ifind\results_market_$RunId.jsonl"
    & $Python (Join-Path $PSScriptRoot 'prepare_ifind_jobs_t1.py') --date $TargetDate --output $Jobs *>>$Log;Assert-Step 'prepare market jobs'
    node (Join-Path $PSScriptRoot 'collect_ifind_incremental.js') --jobs $Jobs --output $Results --concurrency 2 *>>$Log;Assert-Step 'market collection'
    & $Python (Join-Path $PSScriptRoot 'deduplicate_ifind_results.py') --input $Results *>>$Log;Assert-Step 'deduplicate market results'
    & $Python (Join-Path $PSScriptRoot 'ingest_ifind_t1.py') --input $Results --database $Database --date $TargetDate *>>$Log;Assert-Step 'market ingest'
    & $Python (Join-Path $PSScriptRoot 'validate_scale_units.py') --database $Database --date $TargetDate *>>$Log;Assert-Step 'scale validation'
    Write-Status 'running' 'flow' 'collecting direct fund flow only'
    $FlowJobs=Join-Path $Root "data\raw\ifind\jobs_flow_$RunId.json";$FlowResults=Join-Path $Root "data\raw\ifind\results_flow_$RunId.jsonl"
    & $Python (Join-Path $PSScriptRoot 'prepare_ifind_direct_flow_jobs.py') --date $TargetDate --output $FlowJobs *>>$Log;Assert-Step 'prepare flow jobs'
    node (Join-Path $PSScriptRoot 'collect_ifind_incremental.js') --jobs $FlowJobs --output $FlowResults --tool get_fund_ownership --concurrency 2 *>>$Log;Assert-Step 'direct flow collection'
    & $Python (Join-Path $PSScriptRoot 'deduplicate_ifind_results.py') --input $FlowResults *>>$Log;Assert-Step 'deduplicate flow results'
    & $Python (Join-Path $PSScriptRoot 'ingest_ifind_direct_flows.py') --input $FlowResults --database $Database --date $TargetDate *>>$Log;Assert-Step 'direct flow ingest'
    & $Python (Join-Path $PSScriptRoot 'calculate_estimated_flows_v2.py') --database $Database --start $TargetDate --end $TargetDate *>>$Log;Assert-Step 'estimated flow calculation'
    & $Python (Join-Path $PSScriptRoot 'resolve_direct_flows.py') --database $Database --date $TargetDate *>>$Log;Assert-Step 'flow resolution'
    & $Python (Join-Path $PSScriptRoot 'build_dashboard_data.py') --database $Database *>>$Log;Assert-Step 'dashboard build'
    & $Python (Join-Path $PSScriptRoot 'update_indices.py') --start $TargetDate --end $TargetDate *>>$Log;Assert-Step 'domestic indices'
    & $Python (Join-Path $PSScriptRoot 'supplement_kospi.py') --start $TargetDate --end $TargetDate *>>$Log;Assert-Step 'overseas indices'
    & $Python (Join-Path $PSScriptRoot 'normalize_index_labels.py') *>>$Log;Assert-Step 'index labels'
    & $Python (Join-Path $PSScriptRoot 'apply_publication_cutoff.py') --date $TargetDate *>>$Log;Assert-Step 'publication cutoff'
    & $Python (Join-Path $PSScriptRoot 'export_web_data.py') *>>$Log;Assert-Step 'web export'
    & $Python (Join-Path $PSScriptRoot 'build_radar_web_data.py') *>>$Log;Assert-Step 'radar export'
    & $Python (Join-Path $PSScriptRoot 'build_macro_monitor_data.py') --target-date $TargetDate *>>$Log;Assert-Step 'macro export'
    & $Python (Join-Path $PSScriptRoot 'sync_authoritative_cache.py') --database $Database *>>$Log;Assert-Step 'authoritative cache sync'
    & $Python (Join-Path $PSScriptRoot 'build_stable_fund_behavior_data.py') *>>$Log;Assert-Step 'stable fund behavior'
    & $Python (Join-Path $PSScriptRoot 'overlay_tracking_indices.py') *>>$Log;Assert-Step 'tracking index overlay'
    & $Python (Join-Path $PSScriptRoot 'enrich_web_meta.py') *>>$Log;Assert-Step 'web metadata'
  }
  Write-Status 'running' 'validate' 'validating synchronized web publication'
  & $Python (Join-Path $PSScriptRoot 'validate_t1_synchronized.py') --database $Database --date $TargetDate *>>$Log;Assert-Step 'synchronized validation'
  Write-Status 'pass' 'complete' 'one trading day published successfully'
}catch{Write-Status 'failed' 'error' $_.Exception.Message;throw}
