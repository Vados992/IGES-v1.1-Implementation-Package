param([switch]$Administrator)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$settingsPath = Join-Path $repoRoot 'work/windows-pilot/private/settings.json'
$settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
if ($Administrator) {
    Write-Host 'Username: iges-admin-owner'
    Write-Host ('Initial password (change at first login): ' + $settings.owner_password)
    Write-Host 'Enroll your own authenticator to finish management access.'
    Start-Process 'https://localhost:8443/admin/master/console/'
    return
}
Write-Host 'Username: iges-operator'
Write-Host ('Initial password (change at first login): ' + $settings.operator_password)
Write-Host 'Enroll your own authenticator when Keycloak requests OTP configuration.'
Write-Host 'Windows trust was not changed; the browser may show a localhost certificate warning.'
Push-Location -LiteralPath $repoRoot
try {
    & (Join-Path $repoRoot '.venv/Scripts/python.exe') -m scripts.desktop_login
    if ($LASTEXITCODE -ne 0) { throw 'Sign-in not completed.' }
} finally { Pop-Location }
