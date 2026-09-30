$ErrorActionPreference = "Stop"
$dir = Join-Path $PSScriptRoot "..\integration\mariadb"
Push-Location $dir
try {
    if (-not (Test-Path ".env")) {
        Copy-Item ".env.example" ".env"
        Write-Host ""
        Write-Host "Created integration\mariadb\.env"
        Write-Host "Edit the two example passwords before starting the database."
        Write-Host ""
        exit 1
    }
    docker compose up -d
    docker compose ps
}
finally {
    Pop-Location
}
