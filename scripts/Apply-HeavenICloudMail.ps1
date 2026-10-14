# Install/update the local read-only stdio MCP product without touching account data.
# This is NOT a publicly authenticated ChatGPT remote deployment.
[CmdletBinding()]
param([string]$RepoRoot = (Join-Path $PSScriptRoot '..'), [string]$ExpectedSha = '')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA unavailable: no approved per-user install root' }
$InstallRoot = Join-Path $env:LOCALAPPDATA 'HeavenICloudMail'
$Releases = Join-Path $InstallRoot 'releases'
$Pointer = Join-Path $InstallRoot 'current.sha'

function Git-Read([string[]]$Arguments) {
    $out = & git -C $RepoRoot @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) { throw 'Git source verification failed' }
    return ($out | Out-String).Trim()
}

if ((Git-Read -Arguments @('rev-parse','--show-toplevel')) -ne $RepoRoot) { throw 'Repo root mismatch' }
$origin = Git-Read -Arguments @('remote','get-url','origin')
if ($origin -notmatch '^(https://github\.com/fengie/heaven-icloud-mail(\.git)?|git@github\.com:fengie/heaven-icloud-mail\.git)$') {
    throw 'Expected canonical GitHub source origin'
}
if ((Git-Read -Arguments @('branch','--show-current')) -cne 'main') { throw 'Only canonical main may be installed' }
if ((Git-Read -Arguments @('status','--porcelain')) -ne '') { throw 'Source is dirty; refusing to update' }
$Sha = Git-Read -Arguments @('rev-parse','HEAD')
if ($Sha -notmatch '^[0-9a-f]{40}$') { throw 'Unexpected Git SHA' }
if ($ExpectedSha -and $ExpectedSha -cne $Sha) { throw 'Unexpected source SHA; refusing to install' }

New-Item -ItemType Directory -Force -Path $Releases | Out-Null
$Destination = Join-Path $Releases $Sha
$Stage = Join-Path $InstallRoot ('staging-' + $Sha + '-' + $PID)
$Old = if (Test-Path -LiteralPath $Pointer) { (Get-Content -LiteralPath $Pointer -Raw -Encoding UTF8).Trim() } else { '' }
if ($Old -and $Old -notmatch '^[0-9a-f]{40}$') { throw 'Current installed SHA pointer invalid' }

try {
    if (-not (Test-Path -LiteralPath $Destination -PathType Container)) {
        if (Test-Path -LiteralPath $Stage) { throw 'Staging path is already occupied' }
        # The Python version and PyPI availability are external prerequisites.
        if (Get-Command py -ErrorAction SilentlyContinue) {
            & py -3 -m venv $Stage
        } else {
            & python -m venv $Stage
        }
        if ($LASTEXITCODE -ne 0) { throw 'venv creation failed' }
        $StagePython = Join-Path $Stage 'Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $StagePython -PathType Leaf)) { throw 'Python staging runtime missing' }
        & $StagePython -m pip install --disable-pip-version-check --no-input "${RepoRoot}[mcp]"
        if ($LASTEXITCODE -ne 0) { throw 'Package installation failed' }
        & $StagePython -c 'import heaven_icloud_mail, heaven_icloud_mail.server; assert heaven_icloud_mail.__version__ == "0.1.0"'
        if ($LASTEXITCODE -ne 0) { throw 'Staged runtime verification failed' }
        Move-Item -LiteralPath $Stage -Destination $Destination -ErrorAction Stop
    }
    $RuntimePython = Join-Path $Destination 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $RuntimePython -PathType Leaf)) { throw 'Installed runtime is missing' }
    & $RuntimePython -c 'import heaven_icloud_mail, heaven_icloud_mail.server; assert heaven_icloud_mail.__version__ == "0.1.0"'
    if ($LASTEXITCODE -ne 0) { throw 'Installed runtime failed self-check' }
    # A SHA pointer change is the commit of the release. Old releases remain available for rollback.
    $TempPointer = Join-Path $InstallRoot ('current.' + $PID + '.tmp')
    try {
        [IO.File]::WriteAllText($TempPointer, $Sha + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $TempPointer -Destination $Pointer -Force
    } finally {
        if (Test-Path -LiteralPath $TempPointer) { Remove-Item -LiteralPath $TempPointer -Force }
    }
    if ((Get-Content -LiteralPath $Pointer -Raw -Encoding UTF8).Trim() -cne $Sha) { throw 'Installed source revision readback mismatch' }
    Write-Output ("HEAVEN_ICLOUD_MAIL_LOCAL_INSTALLED " + $Sha)
} catch {
    # Fail closed; a pointer already switched to an invalid release must be rolled back.
    if ($Old -match '^[0-9a-f]{40}$' -and (Test-Path -LiteralPath (Join-Path $Releases $Old) -PathType Container)) {
        [IO.File]::WriteAllText($Pointer, $Old + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
    } elseif (Test-Path -LiteralPath $Pointer) {
        Remove-Item -LiteralPath $Pointer -Force
    }
    throw
} finally {
    # Only clean this execution's exact staging directory, never arbitrary temp paths.
    if (Test-Path -LiteralPath $Stage) { Remove-Item -LiteralPath $Stage -Force -Recurse }
}
