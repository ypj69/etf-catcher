# Optional native iFinD API fallback. This does not log in or consume data quota.
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1') -ErrorAction Stop
$Root=Split-Path -Parent $MyInvocation.MyCommand.Path
$ConfigDir=Join-Path $Root 'config'
New-Item -ItemType Directory -Path $ConfigDir -Force|Out-Null
Write-Host 'Configure YOUR iFinD native data-interface account (not an MCP token).'
Write-Host 'This enables account-quota native fallback for ETF ownership when MCP quota is exhausted.'
$Username=Read-Host 'Native API username'
$Password=Read-Host 'Native API password (hidden)' -AsSecureString
if([string]::IsNullOrWhiteSpace($Username) -or $Password.Length -eq 0){throw 'Username and password are required; configuration was not changed.'}
$Pointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($Password)
try{
  $Payload=@{username=$Username;password=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($Pointer)}|ConvertTo-Json -Compress
  $SecurePayload=ConvertTo-SecureString -String $Payload -AsPlainText -Force
  $Encrypted=ConvertFrom-SecureString -SecureString $SecurePayload
  $Encrypted|Set-Content -LiteralPath (Join-Path $ConfigDir 'ifind-native.local.dpapi') -Encoding ascii
}finally{
  [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Pointer)
  $Payload=$null
  $SecurePayload=$null
  $Password=$null
}
Write-Host 'Saved with current-user Windows DPAPI. Install/verify the official SDK in .venv as described in README.'
Write-Host 'No scheduled tasks were changed. No authentication or data request was performed.'
