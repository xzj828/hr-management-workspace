$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backend = Join-Path $projectRoot "backend"
$venvPython = if ($env:HR_PYTHON) { $env:HR_PYTHON } else { Join-Path $projectRoot ".venv\Scripts\python.exe" }
if (-not (Test-Path -LiteralPath $venvPython)) {
    $worktreeParentPython = Join-Path (Split-Path (Split-Path $projectRoot -Parent) -Parent) ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $worktreeParentPython) { $venvPython = $worktreeParentPython }
}
$startScript = Join-Path $PSScriptRoot "start-local.ps1"
$testPort = 8768
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("hr-rpa-startup-" + [guid]::NewGuid().ToString("N"))
$testDatabase = Join-Path $tempRoot "startup.sqlite3"
$launcher = $null
$createdProcessIds = @()

New-Item -ItemType Directory -Path $tempRoot | Out-Null

try {
    $env:DATABASE_PATH = $testDatabase
    $env:HR_PORT = "$testPort"
    $env:HR_NO_CLEAR = "1"
    $env:RPA_API_BASE_URL = "http://127.0.0.1:$testPort/api/recruitment/worker"
    $env:RPA_POLL_SECONDS = "0.5"
    $env:HR_PYTHON = $venvPython

    & $venvPython (Join-Path $backend "manage.py") migrate --noinput | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Temporary database migration failed." }

    $launcher = Start-Process -FilePath "powershell.exe" -WindowStyle Hidden -PassThru -WorkingDirectory $projectRoot -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $startScript
    )

    $deadline = [DateTime]::UtcNow.AddSeconds(35)
    $webReady = $false
    $heartbeatReady = $false
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$testPort/api/auth/csrf/" -TimeoutSec 2
            $webReady = $response.StatusCode -eq 200
        } catch { $webReady = $false }

        $workerCountOutput = & $venvPython (Join-Path $backend "manage.py") shell -c "from recruitment.models import RpaWorker; print('WORKERS=' + str(RpaWorker.objects.filter(status='online').count()))" 2>$null
        $heartbeatReady = [bool]($workerCountOutput -match "WORKERS=1")
        if ($webReady -and $heartbeatReady) { break }
        if ($launcher.HasExited) { break }
        Start-Sleep -Milliseconds 500
    }

    if (-not $webReady) { throw "Web service did not become ready on temporary port $testPort." }
    if (-not $heartbeatReady) { throw "RPA Worker heartbeat was not recorded." }

    $children = @(Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $launcher.Id })
    $createdProcessIds = @($children | Select-Object -ExpandProperty ProcessId)
    $workerProcesses = @($children | Where-Object { $_.CommandLine -like "*run_rpa_worker*" })
    if ($workerProcesses.Count -ne 1) { throw "Expected exactly one RPA Worker process, found $($workerProcesses.Count)." }

    Write-Host "Startup smoke test passed: web service and one RPA Worker are healthy." -ForegroundColor Green
} finally {
    foreach ($processId in $createdProcessIds) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    if ($launcher -and -not $launcher.HasExited) {
        Stop-Process -Id $launcher.Id -Force -ErrorAction SilentlyContinue
    }
    Remove-Item Env:DATABASE_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:HR_PORT -ErrorAction SilentlyContinue
    Remove-Item Env:HR_NO_CLEAR -ErrorAction SilentlyContinue
    Remove-Item Env:RPA_API_BASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:RPA_POLL_SECONDS -ErrorAction SilentlyContinue
    Remove-Item Env:HR_PYTHON -ErrorAction SilentlyContinue
    $resolvedTemp = [System.IO.Path]::GetFullPath($tempRoot)
    $resolvedBase = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
    if ($resolvedTemp.StartsWith($resolvedBase, [System.StringComparison]::OrdinalIgnoreCase) -and (Split-Path $resolvedTemp -Leaf) -like "hr-rpa-startup-*") {
        Remove-Item -LiteralPath $resolvedTemp -Recurse -Force -ErrorAction SilentlyContinue
    }
}
