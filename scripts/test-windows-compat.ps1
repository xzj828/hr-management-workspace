$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$setupScriptPath = Join-Path $PSScriptRoot "setup-local.ps1"
$setupScript = Get-Content -LiteralPath $setupScriptPath -Raw
$startupTestPath = Join-Path $PSScriptRoot "test-startup.ps1"
$startupTest = Get-Content -LiteralPath $startupTestPath -Raw

if ($setupScript -match 'C:\\Users\\[^\\"'']+') {
    throw "setup-local.ps1 contains a hard-coded Windows user profile path."
}

if ($setupScript -notmatch 'Test-VenvPython') {
    throw "setup-local.ps1 does not validate whether a copied virtual environment is usable."
}

if ((Get-ChildItem -LiteralPath $projectRoot -Filter "*.cmd" -File).Count -lt 4) {
    throw "The project root must contain the four Windows command launchers."
}

foreach ($targetScript in @("setup-local.ps1", "start-local.ps1", "change-password.ps1", "backup-local.ps1")) {
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $targetScript))) {
        throw "Missing Windows launcher target: $targetScript"
    }
}

if ($startupTest -notmatch '/static/assets/') {
    throw "test-startup.ps1 does not validate the frontend assets referenced by the served HTML."
}

if ($startupTest -notmatch 'Content-Type') {
    throw "test-startup.ps1 does not reject frontend assets served with an HTML MIME type."
}

Write-Host "Windows compatibility checks passed."
