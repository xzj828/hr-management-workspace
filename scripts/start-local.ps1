$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backend = Join-Path $projectRoot "backend"
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$database = Join-Path $backend "db.sqlite3"
$frontendIndex = Join-Path $backend "frontend_dist\index.html"

$Host.UI.RawUI.WindowTitle = "XM Attendance - Running (keep this window open)"

if (-not (Test-Path -LiteralPath $venvPython)) { throw "System is not initialized. Run the initialization launcher first." }
if (-not (Test-Path -LiteralPath $database)) { throw "Local database is missing. Run the initialization launcher first." }
if (-not (Test-Path -LiteralPath $frontendIndex)) { throw "Frontend build is missing. Run the initialization launcher first." }

$env:DJANGO_DEBUG = "0"
$env:DJANGO_ALLOWED_HOSTS = "*"
Set-Location $backend

$localAddresses = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254*" } |
    Select-Object -ExpandProperty IPAddress -Unique

Clear-Host
Write-Host "============================================================" -ForegroundColor DarkCyan
Write-Host "  XM Attendance is running" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor DarkCyan
Write-Host "Local access: http://127.0.0.1:8000" -ForegroundColor Green
foreach ($address in $localAddresses) {
    Write-Host "LAN access: http://${address}:8000" -ForegroundColor Green
}
Write-Host ""
Write-Host "Keep this terminal open. Close it or press Ctrl+C to stop." -ForegroundColor Yellow
Write-Host "Runtime log:" -ForegroundColor Gray

while ($true) {
    & $venvPython -m waitress --listen=0.0.0.0:8000 --threads=8 config.wsgi:application
    $exitCode = $LASTEXITCODE
    if ($exitCode -eq 0) { break }
    Write-Host "Service stopped with code $exitCode. Restarting in 3 seconds; press Ctrl+C to stop." -ForegroundColor Red
    Start-Sleep -Seconds 3
}
