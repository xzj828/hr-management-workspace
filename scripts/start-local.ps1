$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backend = Join-Path $projectRoot "backend"
$frontend = Join-Path $projectRoot "frontend"
$venvPython = if ($env:HR_PYTHON) { $env:HR_PYTHON } else { Join-Path $projectRoot ".venv\Scripts\python.exe" }
$database = if ($env:DATABASE_PATH) { [System.IO.Path]::GetFullPath($env:DATABASE_PATH) } else { Join-Path $backend "db.sqlite3" }
$frontendIndex = Join-Path $backend "frontend_dist\index.html"
$port = if ($env:HR_PORT) { [int]$env:HR_PORT } else { 8000 }
$webProcess = $null
$workerProcess = $null
$aiWorkerProcess = $null

try { $Host.UI.RawUI.WindowTitle = "XM HR - Running (keep this window open)" } catch {}

if (-not (Test-Path -LiteralPath $venvPython)) { throw "System is not initialized. Run the initialization launcher first." }
if (-not (Test-Path -LiteralPath $database)) { throw "Local database is missing. Run the initialization launcher first." }
if (-not (Test-Path -LiteralPath $frontendIndex)) { throw "Frontend build is missing. Run the initialization launcher first." }

$env:DJANGO_DEBUG = "0"
$env:DJANGO_ALLOWED_HOSTS = "*"
$env:DATABASE_PATH = $database
$env:RPA_API_BASE_URL = "http://127.0.0.1:$port/api/recruitment/worker"

if ($env:HR_BUILD_FRONTEND -eq "1") {
    Push-Location $frontend
    try {
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw "Frontend production build failed." }
    } finally {
        Pop-Location
    }
}

& $venvPython (Join-Path $backend "manage.py") migrate --noinput
if ($LASTEXITCODE -ne 0) { throw "Database migration failed." }
& $venvPython (Join-Path $backend "manage.py") collectstatic --noinput
if ($LASTEXITCODE -ne 0) { throw "Frontend static collection failed." }

$localAddresses = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254*" } |
    Select-Object -ExpandProperty IPAddress -Unique

if (-not $env:HR_NO_CLEAR) { Clear-Host }
Write-Host "============================================================" -ForegroundColor DarkCyan
Write-Host "  XM HR is starting" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor DarkCyan

try {
    $webProcess = Start-Process -FilePath $venvPython -WindowStyle Hidden -PassThru -WorkingDirectory $backend -ArgumentList @(
        "-m", "waitress", "--listen=0.0.0.0:$port", "--threads=8", "config.wsgi:application"
    )

    $deadline = [DateTime]::UtcNow.AddSeconds(25)
    $webReady = $false
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($webProcess.HasExited) { throw "Web service stopped during startup with code $($webProcess.ExitCode)." }
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$port/api/auth/csrf/" -TimeoutSec 2
            if ($response.StatusCode -eq 200) { $webReady = $true; break }
        } catch {}
        Start-Sleep -Milliseconds 350
    }
    if (-not $webReady) { throw "Web service startup timed out." }

    $workerProcess = Start-Process -FilePath $venvPython -WindowStyle Hidden -PassThru -WorkingDirectory $backend -ArgumentList @(
        "manage.py", "run_rpa_worker"
    )
    Start-Sleep -Milliseconds 800
    if ($workerProcess.HasExited) { throw "RPA Worker stopped during startup with code $($workerProcess.ExitCode)." }

    $aiWorkerProcess = Start-Process -FilePath $venvPython -WindowStyle Hidden -PassThru -WorkingDirectory $backend -ArgumentList @(
        "manage.py", "run_ai_worker"
    )
    Start-Sleep -Milliseconds 500
    if ($aiWorkerProcess.HasExited) { throw "AI Worker stopped during startup with code $($aiWorkerProcess.ExitCode)." }

    Write-Host "Web service: healthy" -ForegroundColor Green
    Write-Host "RPA Worker: running" -ForegroundColor Green
    Write-Host "AI Worker: running" -ForegroundColor Green
    Write-Host "Local access: http://127.0.0.1:$port" -ForegroundColor Green
    foreach ($address in $localAddresses) {
        Write-Host "LAN access: http://${address}:$port" -ForegroundColor Green
    }
    Write-Host ""
    Write-Host "Keep this terminal open. Close it or press Ctrl+C to stop both services." -ForegroundColor Yellow

    Wait-Process -Id $webProcess.Id
    throw "Web service stopped unexpectedly with code $($webProcess.ExitCode)."
} finally {
    if ($aiWorkerProcess -and -not $aiWorkerProcess.HasExited) {
        Stop-Process -Id $aiWorkerProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($workerProcess -and -not $workerProcess.HasExited) {
        Stop-Process -Id $workerProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($webProcess -and -not $webProcess.HasExited) {
        Stop-Process -Id $webProcess.Id -Force -ErrorAction SilentlyContinue
    }
}
