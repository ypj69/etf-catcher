param(
  [Parameter(Mandatory=$true)][string]$Python,
  [Parameter(Mandatory=$true)][string]$Database,
  [Parameter(Mandatory=$true)][string]$TargetDate,
  [Parameter(Mandatory=$true)][string]$StartDate
)
$ErrorActionPreference='Stop'
$Root=Split-Path -Parent $PSScriptRoot
function Assert-Step($Name){if($LASTEXITCODE-ne 0){throw "$Name failed with exit code $LASTEXITCODE"}}

& $Python (Join-Path $PSScriptRoot 'build_dashboard_data.py') --database $Database
Assert-Step 'dashboard build'
& $Python (Join-Path $PSScriptRoot 'update_indices.py') --start $StartDate --end $TargetDate
Assert-Step 'domestic indices'
& $Python (Join-Path $PSScriptRoot 'supplement_kospi.py') --start $StartDate --end $TargetDate
Assert-Step 'overseas indices'
& $Python (Join-Path $PSScriptRoot 'normalize_index_labels.py')
Assert-Step 'index labels'
& $Python (Join-Path $PSScriptRoot 'apply_publication_cutoff.py') --date $TargetDate
Assert-Step 'publication cutoff'
& $Python (Join-Path $PSScriptRoot 'export_web_data.py')
Assert-Step 'web export'
& $Python (Join-Path $PSScriptRoot 'build_radar_web_data.py')
Assert-Step 'radar export'
& $Python (Join-Path $PSScriptRoot 'build_macro_monitor_data.py') --target-date $TargetDate
Assert-Step 'macro export'
& $Python (Join-Path $PSScriptRoot 'sync_authoritative_cache.py') --database $Database
Assert-Step 'authoritative cache sync'
& $Python (Join-Path $PSScriptRoot 'build_stable_fund_behavior_data.py')
Assert-Step 'stable fund behavior'
& $Python (Join-Path $PSScriptRoot 'overlay_tracking_indices.py')
Assert-Step 'tracking index overlay'
& $Python (Join-Path $PSScriptRoot 'enrich_web_meta.py')
Assert-Step 'web metadata'
& $Python (Join-Path $PSScriptRoot 'validate_t1_synchronized.py') --database $Database --date $TargetDate
Assert-Step 'synchronized validation'