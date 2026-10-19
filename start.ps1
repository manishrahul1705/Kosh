$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$env:APP_ENV = 'development'
$env:SCHEDULER_ENABLED = 'false'
$env:AUTO_MIGRATE = 'false'
$env:COLLECT_ON_STARTUP = 'false'
$env:STARTUP_RECOVERY_ENABLED = 'false'
$env:DEV_LOGIN_ENABLED = 'true'
$env:KOSH_AUTO_BOOTSTRAP = 'true'
$env:KOSH_AS_OF_DATE = '2026-10-13'
$env:VITE_DEV_LOGIN = 'true'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = (Get-Command python).Source }
$api = $null
$web = $null
try {
    $api = Start-Process -FilePath $python -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8010' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru
    $web = Start-Process -FilePath (Get-Command node).Source -ArgumentList 'node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5180','--strictPort' -WorkingDirectory (Join-Path $PSScriptRoot 'frontend') -WindowStyle Hidden -PassThru
    Write-Host 'Preparing the business workspace. The first start may take a few minutes.'
    $ready = $false
    while (-not $api.HasExited -and -not $web.HasExited) {
        if (-not $ready) {
            try {
                $health = Invoke-WebRequest -Uri 'http://127.0.0.1:8010/health' -UseBasicParsing -TimeoutSec 2
                if ($health.StatusCode -eq 200) { Write-Host 'Open http://127.0.0.1:5180/login - click Sign in.'; $ready = $true }
            } catch { }
        }
        Start-Sleep -Seconds 1
    }
    throw 'A server stopped. Check that dependencies are installed and ports 8010/5180 are available.'
}
finally {
    foreach ($server in @($api,$web)) {
        if ($null -ne $server -and -not $server.HasExited) { & taskkill.exe /PID $server.Id /T /F | Out-Null }
    }
}
