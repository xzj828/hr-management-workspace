$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backupRoot = Join-Path $projectRoot "backups"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$target = Join-Path $backupRoot $stamp
New-Item -ItemType Directory -Force -Path $target | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot "backend\db.sqlite3") -Destination (Join-Path $target "db.sqlite3")
$media = Join-Path $projectRoot "backend\media"
if (Test-Path -LiteralPath $media) {
    Copy-Item -LiteralPath $media -Destination (Join-Path $target "media") -Recurse
}
Write-Host "Backup completed: $target" -ForegroundColor Green
