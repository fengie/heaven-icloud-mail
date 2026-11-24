$ErrorActionPreference = 'Stop'
$validator = Join-Path $PSScriptRoot 'Test-RepoUpdatePolicy.ps1'
$source = Get-Content -LiteralPath (Join-Path $PSScriptRoot '../.heaven/update-policy.json') -Raw -Encoding UTF8
$fixture = [IO.Path]::GetTempFileName()
try {
  $valid = '"heaven-toolbox/repo-autoupdate"'
  $cases = @('missing','null','false','""','"other/controller"','"HEAVEN-TOOLBOX/repo-autoupdate"','{}','[]','["heaven-toolbox/repo-autoupdate"]',$valid)
  $tested = 0
  foreach ($literal in $cases) {
    $policy = $source | ConvertFrom-Json
    if ($literal -ceq 'missing') {
      $policy.source_update.PSObject.Properties.Remove('controller')
      $json = $policy | ConvertTo-Json -Depth 10
    } else {
      $policy.source_update.controller = '__controller_fixture__'
      $json = ($policy | ConvertTo-Json -Depth 10).Replace('"__controller_fixture__"', $literal)
    }
    [IO.File]::WriteAllText($fixture, $json, [Text.UTF8Encoding]::new($false))
    $failure = $null
    $output = $null
    try { $output = & $validator -PolicyPath $fixture } catch { $failure = $_.Exception.Message }
    if ($literal -ceq $valid) {
      if ($failure -or $output -cne 'HEAVEN_AUTOUPDATE_POLICY_OK') { throw 'VALID_CONTROLLER_REJECTED' }
    } elseif ($failure -cne 'Source update controller mismatch.') {
      throw ('INVALID_CONTROLLER_ACCEPTED: ' + $literal)
    }
    $tested++
  }
  if ($tested -ne $cases.Count) { throw 'CONTROLLER_FIXTURES_NOT_EXECUTED' }
  "HEAVEN_AUTOUPDATE_CONTROLLER_TESTS_PASSED count=$tested"
} finally {
  Remove-Item -LiteralPath $fixture -Force
}
