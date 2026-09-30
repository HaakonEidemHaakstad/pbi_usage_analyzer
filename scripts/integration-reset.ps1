$ErrorActionPreference = "Stop"
$dir = Join-Path $PSScriptRoot "..\integration\mariadb"
Push-Location $dir
try {
    docker compose down -v
    docker compose up -d
    docker compose ps
}
finally {
    Pop-Location
}
