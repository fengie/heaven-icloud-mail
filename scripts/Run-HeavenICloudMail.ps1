# Launch the installed STDIO MCP locally. Does not run an unauthenticated HTTP server.
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA unavailable' }
$root = Join-Path $env:LOCALAPPDATA 'HeavenICloudMail'
$pointer = Join-Path $root 'current.sha'
if (-not (Test-Path -LiteralPath $pointer -PathType Leaf)) { throw 'Heaven iCloud Mail not installed' }
$sha = (Get-Content -LiteralPath $pointer -Raw -Encoding UTF8).Trim()
if ($sha -notmatch '^[0-9a-f]{40}$') { throw 'Invalid current runtime identity' }
$exe = Join-Path (Join-Path (Join-Path $root 'releases') $sha) 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw 'Installed Python runtime missing' }
if ($env:HEAVEN_MAIL_TRANSPORT -and $env:HEAVEN_MAIL_TRANSPORT -ne 'stdio') {
    throw 'Network exposure is disabled'
}
& $exe -m heaven_icloud_mail
if ($LASTEXITCODE -ne 0) { throw 'Local MCP stopped with an error' }
