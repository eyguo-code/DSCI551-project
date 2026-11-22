param(
    [string]$Python,
    [string]$MysqlServer,
    [ValidateRange(1024, 65535)][int]$DatabasePort = 33312,
    [ValidateRange(1024, 65535)][int]$WebPort = 8501,
    [switch]$Verify
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

function Invoke-QuietCommand([string]$Program, [string[]]$Arguments) {
    # Windows PowerShell reports native stderr as an error record even when redirected.
    $ErrorActionPreference = 'Continue'
    $output = & $Program @Arguments 2>$null
    return @{ ExitCode = $LASTEXITCODE; Output = $output }
}

$server = $null
$runtimeLock = $null
$previousDemoEnvironment = @{}
foreach ($name in @('MOVIELENS_DB_HOST', 'MOVIELENS_DB_PORT', 'MOVIELENS_DB_NAME',
                    'MOVIELENS_DB_USER', 'MOVIELENS_DB_PASSWORD', 'MOVIELENS_TEST_MYSQL')) {
    $previousDemoEnvironment[$name] = [Environment]::GetEnvironmentVariable($name)
}
$previousMysqlPassword = $env:MYSQL_PWD
Push-Location -LiteralPath $PSScriptRoot
try {
    if (-not $Python) {
        $venvPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
        if (Test-Path -LiteralPath $venvPython) {
            $Python = $venvPython
        } else {
            $Python = (Get-Command python -ErrorAction Stop).Source
        }
    }
    $packages = Invoke-QuietCommand $Python @('-c', 'import pymysql, streamlit')
    if ($packages.ExitCode -ne 0) {
        throw 'Install the Python dependencies from requirements.txt first. See README.md.'
    }
    if (-not $MysqlServer) {
        $onPath = Get-Command mysqld -ErrorAction SilentlyContinue
        if ($onPath) {
            $MysqlServer = $onPath.Source
        } else {
            $MysqlServer = Get-ChildItem 'C:/Program Files/MySQL/MySQL Server */bin/mysqld.exe' -ErrorAction SilentlyContinue |
                Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
        }
    }
    if (-not $MysqlServer -or -not (Test-Path -LiteralPath $MysqlServer)) {
        throw 'Install MySQL Server 8.4 or newer, or pass the full path to mysqld.exe as -MysqlServer.'
    }

    $mysqlBin = Split-Path -Parent $MysqlServer
    $client = Join-Path $mysqlBin 'mysql.exe'
    $mysqlAdmin = Join-Path $mysqlBin 'mysqladmin.exe'
    $privateDir = Join-Path $PSScriptRoot '.demo'
    $dataDir = Join-Path $privateDir 'mysql'
    $logFile = Join-Path $privateDir 'mysqld.log'
    $credentialsFile = Join-Path $privateDir 'credentials.json'
    $initFile = Join-Path $privateDir 'initialize.sql'
    New-Item -ItemType Directory -Path $privateDir -Force | Out-Null
    try {
        $runtimeLock = [IO.File]::Open((Join-Path $privateDir 'launcher.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    } catch [IO.IOException] {
        throw 'A MovieLens launcher is already running in this folder.'
    }

    if (-not (Test-Path -LiteralPath (Join-Path $dataDir 'auto.cnf'))) {
        New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
        & $MysqlServer --no-defaults --initialize-insecure "--datadir=$dataDir" "--log-error=$logFile"
        if ($LASTEXITCODE -ne 0) { throw "MySQL initialization failed. See $logFile." }
    }
    if (-not (Test-Path -LiteralPath $credentialsFile)) {
        $credentials = @{
            root = [guid]::NewGuid().ToString('N')
            app  = [guid]::NewGuid().ToString('N')
        }
        @"
ALTER USER 'root'@'localhost' IDENTIFIED BY '$($credentials.root)';
CREATE DATABASE IF NOT EXISTS movielens_demo CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER IF NOT EXISTS 'movielens'@'127.0.0.1' IDENTIFIED BY '$($credentials.app)';
GRANT SELECT, CREATE, INSERT, REFERENCES ON movielens_demo.* TO 'movielens'@'127.0.0.1';
"@ | Set-Content -LiteralPath $initFile -Encoding ASCII
        $credentials | ConvertTo-Json | Set-Content -LiteralPath $credentialsFile -Encoding ASCII
    }
    $credentials = Get-Content -LiteralPath $credentialsFile -Raw | ConvertFrom-Json

    $serverArgs = @(
        '--no-defaults', "--datadir=`"$dataDir`"", "--log-error=`"$logFile`"",
        "--port=$DatabasePort", '--bind-address=127.0.0.1', '--mysqlx=OFF', '--skip-log-bin'
    )
    if (Test-Path -LiteralPath $initFile) { $serverArgs += "--init-file=`"$initFile`"" }
    $server = Start-Process -FilePath $MysqlServer -ArgumentList $serverArgs -PassThru -WindowStyle Hidden

    $connectionArgs = @('--no-defaults', '--host=127.0.0.1', "--port=$DatabasePort", '--protocol=TCP')
    $appArgs = $connectionArgs + @('--user=movielens', '--database=movielens_demo')
    $env:MYSQL_PWD = $credentials.app
    $ready = $false
    for ($attempt = 0; $attempt -lt 60 -and -not $server.HasExited; $attempt++) {
        $probe = Invoke-QuietCommand $client ($appArgs + @('--connect-timeout=1', '-Nse', 'SELECT 1'))
        if ($probe.ExitCode -eq 0 -and -not $server.HasExited) {
            $ready = $true
            break
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $ready) { throw "The private MySQL server could not start. See $logFile." }
    if (Test-Path -LiteralPath $initFile) { Remove-Item -LiteralPath $initFile }

    $ratingRows = Invoke-QuietCommand $client ($appArgs + @('-Nse', 'SELECT COUNT(*) FROM ratings'))
    $env:MYSQL_PWD = $previousMysqlPassword
    $env:MOVIELENS_DB_HOST = '127.0.0.1'
    $env:MOVIELENS_DB_PORT = "$DatabasePort"
    $env:MOVIELENS_DB_NAME = 'movielens_demo'
    $env:MOVIELENS_DB_USER = 'movielens'
    $env:MOVIELENS_DB_PASSWORD = $credentials.app
    if ($ratingRows.ExitCode -ne 0 -or $ratingRows.Output -eq '0') {
        & $Python -m movielens.load
        if ($LASTEXITCODE -ne 0) { throw 'The MovieLens import failed.' }
    }

    if ($Verify) {
        $env:MOVIELENS_TEST_MYSQL = '1'
        & $Python -m unittest discover -s tests -v
        if ($LASTEXITCODE -ne 0) { throw 'The demo checks failed.' }
    } else {
        Write-Host "Open http://127.0.0.1:$WebPort. Press Ctrl+C here to stop the demo."
        & $Python -m streamlit run app.py --server.headless=true --server.port=$WebPort
        if ($LASTEXITCODE -ne 0) { throw 'Streamlit exited with an error.' }
    }
} finally {
    try {
        if ($server -and -not $server.HasExited) {
            if ($ready) {
                $env:MYSQL_PWD = $credentials.root
                Invoke-QuietCommand $mysqlAdmin ($connectionArgs + @('--user=root', '--connect-timeout=3', 'shutdown')) |
                    Out-Null
            }
            if (-not $server.WaitForExit(5000)) { Stop-Process -InputObject $server }
        }
    } finally {
        if ($runtimeLock) { $runtimeLock.Dispose() }
        $env:MYSQL_PWD = $previousMysqlPassword
        foreach ($name in $previousDemoEnvironment.Keys) {
            [Environment]::SetEnvironmentVariable($name, $previousDemoEnvironment[$name])
        }
        Pop-Location
    }
}
