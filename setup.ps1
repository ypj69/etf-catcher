param(
  [string]$SeedPath = '',
  [string]$SeedUrl = '',
  [string]$PythonPath = '',
  [switch]$RegisterTasks
)
$ErrorActionPreference='Stop'
$Root=Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv=Join-Path $Root '.venv'
$Python=if($PythonPath){$PythonPath}elseif($env:ETF_CATCHER_PYTHON){$env:ETF_CATCHER_PYTHON}else{$null}
if($Python -and -not (Test-Path -LiteralPath $Python)){throw 'PythonPath does not exist.'}
if(-not $Python){
  foreach($Candidate in @('py','python')){
    $Command=Get-Command $Candidate -ErrorAction SilentlyContinue
    if(-not $Command){continue}
    if($Command.Source -like '*\Microsoft\WindowsApps\python.exe'){continue}
    $Python=$Command.Source
    break
  }
}
if(-not $Python){throw 'Python 3.11 or newer was not found in PATH.'}
if(-not (Test-Path -LiteralPath $Venv)){
  if((Split-Path -Leaf $Python)-eq 'py.exe'){& $Python -3 -m venv $Venv}else{& $Python -m venv $Venv}
  if($LASTEXITCODE-ne 0){throw 'Failed to create the project virtual environment.'}
}
$ProjectPython=Join-Path $Venv 'Scripts\python.exe'
& $ProjectPython -m pip install --disable-pip-version-check --retries 10 --resume-retries 10 --timeout 120 -r (Join-Path $Root 'requirements.txt')
if($LASTEXITCODE-ne 0){throw 'Failed to install Python dependencies.'}

function Find-ReleaseSeedUrl {
  $Git=Get-Command git -ErrorAction SilentlyContinue
  if(-not $Git){return ''}
  $Origin=(& $Git.Source -C $Root remote get-url origin 2>$null)
  if(-not $Origin){return ''}
  $Slug=([string]$Origin).Trim() -replace '\.git$',''
  $Slug=$Slug -replace '^https://github\.com/','' -replace '^git@github\.com:',''
  if($Slug-notmatch '^[^/]+/[^/]+$'){return ''}
  $Release=Invoke-RestMethod -Uri "https://api.github.com/repos/$Slug/releases/latest" -Headers @{'User-Agent'='ETF-Catcher-Setup'}
  $Asset=$Release.assets|Where-Object {$_.name-like 'etf-catcher-seed-*.zip'}|Select-Object -First 1
  if($Asset){return [string]$Asset.browser_download_url}
  return ''
}

$Database=Join-Path $Root 'data\etf_catcher.sqlite3'
if(-not (Test-Path -LiteralPath $Database)){
  if(-not $SeedPath -and -not $SeedUrl){
    try{$SeedUrl=Find-ReleaseSeedUrl}catch{Write-Warning 'Could not discover the latest GitHub seed release automatically.'}
  }
  if($SeedUrl){
    $Download=Join-Path $env:TEMP ('etf-catcher-seed-'+[guid]::NewGuid().ToString('N')+'.zip')
    Invoke-WebRequest -Uri $SeedUrl -OutFile $Download -UseBasicParsing
    $SeedPath=$Download
  }
  if($SeedPath){
    $Resolved=(Resolve-Path -LiteralPath $SeedPath).Path
    if([IO.Path]::GetExtension($Resolved)-eq '.zip'){
      $Extract=Join-Path $env:TEMP ('etf-catcher-seed-'+[guid]::NewGuid().ToString('N'))
      New-Item -ItemType Directory -Path $Extract|Out-Null
      Expand-Archive -LiteralPath $Resolved -DestinationPath $Extract
      $Manifest=Get-ChildItem -LiteralPath $Extract -Recurse -Filter 'seed-manifest.json'|Select-Object -First 1
      $SeedDb=Get-ChildItem -LiteralPath $Extract -Recurse -Filter 'etf_catcher.sqlite3'|Select-Object -First 1
      if(-not $Manifest -or -not $SeedDb){throw 'The seed archive is missing its database or manifest.'}
      $Meta=Get-Content -LiteralPath $Manifest.FullName -Raw -Encoding UTF8|ConvertFrom-Json
      $Hash=(Get-FileHash -LiteralPath $SeedDb.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
      if($Hash-ne ([string]$Meta.database_sha256).ToLowerInvariant()){throw 'Seed database SHA256 verification failed.'}
      Copy-Item -LiteralPath $SeedDb.FullName -Destination $Database
      $Web=Join-Path $Extract 'data\web'
      if(Test-Path -LiteralPath $Web){Get-ChildItem -LiteralPath $Web -Filter '*.json'|Copy-Item -Destination (Join-Path $Root 'data\web') -Force}
      Remove-Item -LiteralPath $Extract -Recurse -Force
    }elseif([IO.Path]::GetExtension($Resolved)-eq '.sqlite3'){
      Copy-Item -LiteralPath $Resolved -Destination $Database
    }else{throw 'SeedPath must point to a .zip or .sqlite3 file.'}
  }else{
    Write-Warning 'No seed database was installed. Run setup.ps1 again with SeedPath or SeedUrl.'
  }
}
if($Download -and (Test-Path -LiteralPath $Download)){Remove-Item -LiteralPath $Download -Force}
if(Test-Path -LiteralPath $Database){
  & $ProjectPython (Join-Path $Root 'tools\validate_install.py')
  if($LASTEXITCODE-ne 0){throw 'Installation validation failed.'}
}
if($RegisterTasks){& (Join-Path $Root 'scripts\register_tasks.ps1')}
Write-Host 'ETF Catcher setup completed. Run configure.ps1 and then start.ps1.' -ForegroundColor Green
