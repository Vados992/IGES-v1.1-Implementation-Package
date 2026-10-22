$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Push-Location -LiteralPath $repoRoot
try {
    & (Join-Path $repoRoot '.venv/Scripts/python.exe') -m scripts.windows_pilot start
    if ($LASTEXITCODE -ne 0) { throw 'IGES startup failed; inspect work/windows-pilot logs.' }
} finally { Pop-Location }
