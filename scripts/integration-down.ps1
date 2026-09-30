$ErrorActionPreference = "Stop"
$dir = Join-Path $PSScriptRoot "..\integration\mariadb"
Push-Location $dir
try {
    docker compose down
}
finally {
    Pop-Location
}
