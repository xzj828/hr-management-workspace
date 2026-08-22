$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backend = Join-Path $projectRoot "backend"
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

$Host.UI.RawUI.WindowTitle = "XM Attendance - Change admin password"

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "System is not initialized. Run the initialization launcher first."
}

Set-Location $backend
Write-Host "The password for the admin account will be changed." -ForegroundColor Cyan
Write-Host "Password characters are intentionally hidden while typing." -ForegroundColor Yellow
& $venvPython manage.py changepassword admin

if ($LASTEXITCODE -eq 0) {
    Write-Host "Password changed successfully. You may close this window." -ForegroundColor Green
} else {
    throw "Password change failed. Review the message above and retry."
}
