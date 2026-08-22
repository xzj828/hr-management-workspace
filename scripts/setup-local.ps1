param(
    [string]$ReferencePath = "",
    [string]$AdminUsername = "admin"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backend = Join-Path $projectRoot "backend"
$frontend = Join-Path $projectRoot "frontend"
$venv = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

function Test-VenvPython {
    param([string]$PythonPath)
    if (-not (Test-Path -LiteralPath $PythonPath)) { return $false }
    & $PythonPath -c "import sys; print(sys.executable)" *> $null
    return $LASTEXITCODE -eq 0
}

function Assert-NativeSuccess {
    param([string]$Step)
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE."
    }
}

Write-Host "[1/6] Locating Python runtime" -ForegroundColor Cyan
$python = $null
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($pythonCommand) { $python = $pythonCommand.Source }
if (-not $python) {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        $python = (& $pyLauncher.Source -3 -c "import sys; print(sys.executable)" 2>$null | Select-Object -Last 1)
    }
}
if (-not $python -or -not (Test-Path -LiteralPath $python)) {
    throw "Python 3 was not found. Install Python 3.12 or newer and retry."
}

if ((Test-Path -LiteralPath $venv) -and -not (Test-VenvPython -PythonPath $venvPython)) {
    Write-Host "The copied virtual environment belongs to another computer and will be rebuilt." -ForegroundColor Yellow
    $resolvedVenv = (Resolve-Path -LiteralPath $venv).Path
    $expectedVenv = [System.IO.Path]::GetFullPath($venv)
    if ($resolvedVenv -ne $expectedVenv -or (Split-Path -Leaf $resolvedVenv) -ne ".venv") {
        throw "Refusing to remove an unexpected virtual environment path: $resolvedVenv"
    }
    Remove-Item -LiteralPath $resolvedVenv -Recurse -Force
}

if (-not (Test-VenvPython -PythonPath $venvPython)) {
    & $python -m venv $venv
    Assert-NativeSuccess "Creating the Windows virtual environment"
}

Write-Host "[2/6] Installing Python dependencies" -ForegroundColor Cyan
& $venvPython -m pip install -r (Join-Path $backend "requirements.txt")
Assert-NativeSuccess "Installing Python dependencies"

Write-Host "[3/6] Installing and building the Vue 3 frontend" -ForegroundColor Cyan
$npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npm) { $npm = Get-Command npm -ErrorAction SilentlyContinue }
if (-not $npm) { throw "Node.js/npm was not found. Install the current Node.js LTS release and retry." }
Push-Location $frontend
try {
    & $npm.Source install
    Assert-NativeSuccess "Installing frontend dependencies"
    & $npm.Source run build
    Assert-NativeSuccess "Building the frontend"
} finally {
    Pop-Location
}

Write-Host "[4/6] Initializing the local SQLite database" -ForegroundColor Cyan
& $venvPython (Join-Path $backend "manage.py") migrate
Assert-NativeSuccess "Applying database migrations"

$securePassword = Read-Host "Set the admin password (at least 10 characters)" -AsSecureString
$passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
try {
    $adminPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
}

Write-Host "[5/6] Creating the administrator and default rules" -ForegroundColor Cyan
$setupArgs = @("setup_system", "--admin-username", $AdminUsername, "--admin-password", $adminPassword)
if (-not $ReferencePath) {
    $downloads = Join-Path ([Environment]::GetFolderPath("UserProfile")) "Downloads"
    $candidate = Get-ChildItem -LiteralPath $downloads -Filter "2026.4*.xlsx" -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($candidate) { $ReferencePath = $candidate.FullName }
}
if ($ReferencePath -and (Test-Path -LiteralPath $ReferencePath)) {
    $setupArgs += @("--reference", $ReferencePath)
}
& $venvPython (Join-Path $backend "manage.py") @setupArgs
Assert-NativeSuccess "Creating the administrator and default rules"

Write-Host "[6/6] Collecting frontend static assets" -ForegroundColor Cyan
$env:DJANGO_DEBUG = "0"
& $venvPython (Join-Path $backend "manage.py") collectstatic --noinput
Assert-NativeSuccess "Collecting static assets"

Write-Host "Initialization complete. Run the attendance launcher to start the system." -ForegroundColor Green
