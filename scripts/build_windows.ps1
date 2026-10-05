# Build the standalone Windows application (one folder + zip) and smoke-test it.
# Usage: powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1 [-OutDir <folder>]
# Needs: .venv with requirements-build.txt installed.
# Tip: if the repository is in OneDrive, pass an -OutDir outside it so the
# build output is not synced.
param(
    [string]$OutDir = "",
    [switch]$SkipSmokeTest
)

$ErrorActionPreference = "Stop"

# Drive an MCP server executable over stdio: handshake, tool list, one analysis.
function Test-McpServer([string]$Executable, [string[]]$Arguments, [string]$Project, [string]$StateDir) {
    $pathJson = ($Project | ConvertTo-Json)
    $requests = @(
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25"}}',
        '{"jsonrpc":"2.0","method":"notifications/initialized"}',
        '{"jsonrpc":"2.0","id":2,"method":"tools/list"}',
        ('{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"analyze_model","arguments":{"project_path":' + $pathJson + ',"sections":["project"]}}}')
    )
    $replies = @($requests | & $Executable @Arguments --data-dir $StateDir)
    $exitCode = $LASTEXITCODE
    $ids = @($replies | ForEach-Object { ($_ | ConvertFrom-Json).id })
    $analysis = ($replies[2] | ConvertFrom-Json).result
    if ($exitCode -ne 0 -or ($ids -join ",") -ne "1,2,3" -or $analysis.isError -or
            -not $analysis.content[0].text.Contains("<analysis>")) {
        throw "MCP smoke test of $Executable failed (exit code $exitCode): $($replies -join ' | ')"
    }
}
$root = Split-Path -Parent $PSScriptRoot
if (-not $OutDir) { $OutDir = Join-Path $root "dist" }
$OutDir = [System.IO.Path]::GetFullPath($OutDir)
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "No .venv found. Run scripts\bootstrap.ps1 -Gui first." }

Push-Location $root
try {
    & $python -c "import PyInstaller, PySide6, packaging" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Build dependencies missing. Run: .\.venv\Scripts\python.exe -m pip install -r requirements-build.txt"
    }
    $version = (& $python -c "import pbi_usage_analyzer; print(pbi_usage_analyzer.__version__)").Trim()
    Write-Host "Building PBI Model Health $version into $OutDir"

    & $python -m PyInstaller packaging\pbi_model_health.spec --noconfirm --clean `
        --distpath $OutDir --workpath (Join-Path $OutDir ".build")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }
    $app = Join-Path $OutDir "PBI Model Health"
    & $python packaging\write_notices.py $app
    if ($LASTEXITCODE -ne 0) { throw "Writing license notices failed." }
    # No network components, no missing DLL dependencies.
    & $python packaging\check_bundle.py $app
    if ($LASTEXITCODE -ne 0) { throw "Bundle check failed." }

    # Claude Desktop extension: a separate, Qt-free build of the MCP server.
    & $python -m PyInstaller packaging\pbi_model_health_mcp.spec --noconfirm --clean `
        --distpath $OutDir --workpath (Join-Path $OutDir ".build-mcp")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed for the MCP server." }
    $server = Join-Path $OutDir "pbi-model-health-mcp"
    & $python packaging\write_notices.py --server $server
    if ($LASTEXITCODE -ne 0) { throw "Writing the server's notices failed." }
    & $python packaging\check_bundle.py $server
    if ($LASTEXITCODE -ne 0) { throw "Bundle check of the MCP server failed." }

    if (-not $SkipSmokeTest) {
        # Run the frozen app headless on a synthetic project: analysis, main window, export.
        $work = Join-Path ([System.IO.Path]::GetTempPath()) ("pbi_smoke_" + [guid]::NewGuid().ToString("N"))
        $project = Join-Path $work "project"
        $output = Join-Path $work "out"
        Copy-Item -Recurse "tools\validation\validation_suite\41_m_usage_aware_lineage" $project
        $previous = $env:QT_QPA_PLATFORM
        $env:QT_QPA_PLATFORM = "offscreen"
        try {
            $process = Start-Process -FilePath (Join-Path $app "PBI Model Health.exe") -Wait -PassThru `
                -ArgumentList @("--smoke-test", "`"$project`"", "`"$output`"")
        } finally {
            $env:QT_QPA_PLATFORM = $previous
        }
        $summary = Join-Path $output "smoke-test.json"
        if ($process.ExitCode -ne 0 -or -not (Test-Path $summary)) {
            $errorFile = Join-Path $output "smoke-test-error.txt"
            if (Test-Path $errorFile) { Get-Content $errorFile | Write-Host }
            throw "Smoke test of the built application failed (exit code $($process.ExitCode))."
        }
        Write-Host "Smoke test passed:"
        Get-Content $summary | Write-Host

        # Console companion: reports for the same project, no window.
        $cliOutput = Join-Path $work "cli"
        $env:PBI_NO_PAUSE = "1"
        try {
            & (Join-Path $app "pbi-model-health-cli.exe") $project --out $cliOutput | Write-Host
            $cliExit = $LASTEXITCODE
        } finally {
            Remove-Item Env:PBI_NO_PAUSE
        }
        if ($cliExit -ne 0 -or -not (Get-ChildItem $cliOutput -Filter "*_usage_summary_v2.txt" -ErrorAction SilentlyContinue)) {
            throw "Console smoke test failed (exit code $cliExit)."
        }
        Write-Host "Console smoke test passed."

        # MCP server for Claude Desktop, in the app and in the extension's own build.
        Test-McpServer (Join-Path $app "pbi-model-health-cli.exe") @("--mcp") $project (Join-Path $work "mcp-state")
        Test-McpServer (Join-Path $server "pbi-model-health-mcp.exe") @() $project (Join-Path $work "mcp-state")
        Write-Host "MCP smoke tests passed."
        Remove-Item -Recurse -Force $work
    }

    $zip = Join-Path $OutDir "PBI-Model-Health-$version-win64.zip"
    if (Test-Path $zip) { Remove-Item -Force $zip }
    Compress-Archive -Path $app -DestinationPath $zip
    $size = [math]::Round((Get-Item $zip).Length / 1MB, 1)
    $extension = Join-Path $OutDir "PBI-Model-Health-$version.mcpb"
    & $python packaging\build_mcpb.py $server $extension
    if ($LASTEXITCODE -ne 0) { throw "Packing the Claude Desktop extension failed." }
    # Checksums for verifying a download (sha256sum format).
    $sums = Join-Path $OutDir "SHA256SUMS.txt"
    $lines = foreach ($file in @($zip, $extension, (Join-Path $app "PBI Model Health.exe"), (Join-Path $app "pbi-model-health-cli.exe"))) {
        "{0}  {1}" -f (Get-FileHash -Algorithm SHA256 $file).Hash.ToLowerInvariant(), (Split-Path -Leaf $file)
    }
    Set-Content -Path $sums -Value $lines -Encoding ascii
    Write-Host "Application folder: $app"
    Write-Host "Zip ($size MB): $zip"
    Write-Host "Claude Desktop extension: $extension"
    Get-Content $sums | Write-Host
} finally {
    Pop-Location
}
