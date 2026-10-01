<#
.SYNOPSIS
  Load the case-study databases into a local MariaDB, create a read-only login
  for Power BI, optionally install the MariaDB ODBC driver, and verify.

.DESCRIPTION
  Interactive: prompts for the MariaDB root password and for a new password for
  the read-only login. Passwords are held as SecureStrings, passed to the client
  through the MYSQL_PWD environment variable of this process only (never on a
  command line or in a file), and cleared afterwards. Re-running is safe: the
  SQL scripts drop and recreate their tables, and the login's password is reset.

  The log (-LogPath) records steps and row counts only, never passwords.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\casestudy\setup_mariadb.ps1 `
      -MessFolder ..\AWCase -GoodFolder ..\AWGood -OdbcMsi $env:TEMP\mariadb-connector-odbc-3.1.23-win64.msi
#>
param(
    [Parameter(Mandatory = $true)][string]$MessFolder,
    [Parameter(Mandatory = $true)][string]$GoodFolder,
    [string]$ReaderUser = "pbi_reader",
    [string]$OdbcMsi = "",
    [string]$LogPath = (Join-Path $env:TEMP "aw_mariadb_setup.log")
)
$ErrorActionPreference = "Stop"

function Log([string]$message) {
    Write-Host $message
    Add-Content -Path $LogPath -Value $message -Encoding UTF8
}

function Plain([Security.SecureString]$secure) {
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

function Invoke-Mysql([string]$user, [Security.SecureString]$password, [string]$sql) {
    # Native stderr must not become a terminating error before the exit code is read.
    $ErrorActionPreference = "Continue"
    $env:MYSQL_PWD = Plain $password
    try {
        # Without --abort-source-on-error, a failing statement inside `source`
        # is skipped silently and the client still exits 0.
        $output = $sql | & $script:mysql --default-character-set=utf8mb4 --abort-source-on-error -u $user -N -B 2>&1
        $errors = @($output | Where-Object { "$_" -match '^ERROR \d+' })
        if ($LASTEXITCODE -ne 0 -or $errors.Count -gt 0) { throw "mysql failed: $($output -join ' ')" }
        return $output
    } finally {
        Remove-Item Env:MYSQL_PWD -ErrorAction SilentlyContinue
    }
}

Set-Content -Path $LogPath -Value "Case-study MariaDB setup $(Get-Date -Format s)" -Encoding UTF8
try {
    # Pipe SQL to the client as UTF-8 (Windows PowerShell defaults to ASCII).
    $OutputEncoding = New-Object System.Text.UTF8Encoding($false)

    $client = Get-ChildItem "C:\Program Files\MariaDB*\bin\mysql.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $client) { throw "MariaDB client not found under C:\Program Files\MariaDB*\bin" }
    $script:mysql = $client.FullName
    Log "Client: $script:mysql"

    $files = @(
        (Join-Path $MessFolder "mariadb\01_schema.sql"), (Join-Path $MessFolder "mariadb\02_data.sql"),
        (Join-Path $MessFolder "mariadb\03_views.sql"),
        (Join-Path $GoodFolder "mariadb\01_schema.sql"), (Join-Path $GoodFolder "mariadb\02_data.sql")
    ) | ForEach-Object { (Resolve-Path $_).Path }

    $root = Read-Host "MariaDB root password" -AsSecureString
    Invoke-Mysql "root" $root "SELECT 1;" | Out-Null
    Log "Root login OK."

    foreach ($file in $files) {
        Log "Loading $file ..."
        Invoke-Mysql "root" $root ("source " + ($file -replace '\\', '/') + ";") | Out-Null
    }

    Write-Host "Read-only login '$ReaderUser': enter a new password (or its current one, to keep it)."
    do {
        $first = Read-Host "Password for '$ReaderUser'" -AsSecureString
        $second = Read-Host "Repeat it" -AsSecureString
        $same = (Plain $first) -ceq (Plain $second) -and $first.Length -gt 0
        if (-not $same) { Write-Host "Empty or not matching; try again." }
    } while (-not $same)
    $literal = "'" + ((Plain $first) -replace '\\', '\\' -replace "'", "''") + "'"
    $account = "'$ReaderUser'@'localhost'"
    Invoke-Mysql "root" $root (
        "CREATE USER IF NOT EXISTS $account IDENTIFIED BY $literal; " +
        "ALTER USER $account IDENTIFIED BY $literal; " +
        "GRANT SELECT ON aw_ops.* TO $account; GRANT SELECT ON aw_dw.* TO $account;") | Out-Null
    $root = $null; $literal = $null; $second = $null
    Log "Login $ReaderUser created/updated with SELECT on aw_ops and aw_dw."

    # Every table must hold exactly the rows its package manifest promises.
    $expected = [ordered]@{}
    foreach ($pair in @(@("aw_ops", $MessFolder), @("aw_dw", $GoodFolder))) {
        $manifest = Get-Content (Join-Path $pair[1] "manifest.json") -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($table in $manifest.mariadb.PSObject.Properties) { $expected["$($pair[0]).$($table.Name)"] = [int]$table.Value }
        foreach ($view in @($manifest.views)) { if ($view) { $expected["$($pair[0]).$view"] = -1 } }
    }
    $query = ($expected.Keys | ForEach-Object { "SELECT '$_', COUNT(*) FROM $_" }) -join " UNION ALL "
    $counts = Invoke-Mysql $ReaderUser $first "$query;"
    $first = $null; $second = $null
    Log "Row counts read as ${ReaderUser} (expected from manifest.json):"
    $mismatches = 0
    foreach ($line in $counts) {
        $name, $count = "$line" -split "`t"
        $want = $expected[$name]
        $ok = ($want -eq -1 -and [int]$count -gt 0) -or ([int]$count -eq $want)
        if (-not $ok) { $mismatches++ }
        $wanted = if ($want -eq -1) { "view, > 0" } else { "$want" }
        Log ("  {0,-30} {1,8}   expected {2}{3}" -f $name, $count, $wanted, $(if ($ok) { "" } else { "   MISMATCH" }))
    }
    if ($mismatches -gt 0) { throw "$mismatches table(s) do not match their manifest." }

    if ($OdbcMsi) {
        $present = Get-OdbcDriver -Platform "64-bit" -ErrorAction SilentlyContinue | Where-Object Name -like "MariaDB ODBC 3.1*"
        if ($present) {
            Log "ODBC driver already installed: $($present.Name)"
        } else {
            $signature = Get-AuthenticodeSignature $OdbcMsi
            if ($signature.Status -ne "Valid") { throw "ODBC installer signature is $($signature.Status); not installing." }
            Log "Installing $OdbcMsi (Windows will ask for administrator approval) ..."
            $process = Start-Process msiexec.exe -ArgumentList "/i `"$OdbcMsi`" /qb /norestart" -Verb RunAs -Wait -PassThru
            Log "msiexec exit code: $($process.ExitCode)"
            $present = Get-OdbcDriver -Platform "64-bit" -ErrorAction SilentlyContinue | Where-Object Name -like "MariaDB ODBC 3.1*"
            if (-not $present) { throw "ODBC driver not registered after installation." }
            Log "ODBC driver installed: $($present.Name)"
        }
    }
    Log "RESULT: OK"
} catch {
    Log "ERROR: $($_.Exception.Message)"
    Log "RESULT: FAILED"
} finally {
    Remove-Item Env:MYSQL_PWD -ErrorAction SilentlyContinue
}
