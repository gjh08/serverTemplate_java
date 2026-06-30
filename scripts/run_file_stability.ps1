# Upload/download stability: start server, run test, verify health
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$jar = Join-Path $root "target\server-template-1.0.0.jar"
$ports = @(17080, 17081, 17082)

foreach ($port in $ports) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}
Start-Sleep -Seconds 2

if (-not (Test-Path $jar)) {
    Push-Location $root
    mvn -q package -DskipTests
    Pop-Location
}

$proc = Start-Process -FilePath "java" -ArgumentList "-Xms512m","-Xmx1g","-jar",$jar `
    -PassThru -WindowStyle Hidden

function Wait-Health {
    for ($i = 0; $i -lt 40; $i++) {
        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:17080/template/health" -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -eq 200) { return $true }
        } catch {}
        Start-Sleep -Seconds 1
    }
    return $false
}

if (-not (Wait-Health)) {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    throw "server failed to start"
}

Push-Location $root
py -3 tests\test_file_stability.py
$code = $LASTEXITCODE
Pop-Location

if (-not $proc.HasExited) {
    if (-not (Wait-Health)) {
        Write-Host "FAIL: process alive but health dead" -ForegroundColor Red
        $code = 1
    }
}

Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
exit $code
