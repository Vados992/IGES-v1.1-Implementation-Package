$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$pilotRoot = Join-Path $repoRoot 'work/windows-pilot'
# Match full task-owned paths; never terminate by a reused PID or process name alone.
$owned = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -in @('python.exe', 'java.exe', 'cmd.exe') -and
    $_.CommandLine -and $_.CommandLine.Contains($pilotRoot)
}
foreach ($process in $owned) {
    Stop-Process -Id $process.ProcessId -ErrorAction SilentlyContinue
}
$pgCtl = Join-Path $pilotRoot 'database/pgsql/bin/pg_ctl.exe'
if (Test-Path -LiteralPath $pgCtl) {
    & $pgCtl -D (Join-Path $pilotRoot 'private/postgres') -m fast -w stop
}
Write-Output 'Stopped the isolated IGES pilot; files and data were retained.'
