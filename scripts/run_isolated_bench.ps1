# Isolated benchmark: one server at a time, then merge comparison report
param(
    [string]$Concurrency = "100,400,1000,2000",
    [int]$Count = 8000,
    [string]$Title = "bench-isolated-report",
    [string]$Report = "bench_report_section.md"
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$benchDir = Join-Path $root "bench_data"
$templateJar = Join-Path $root "target\server-template-1.0.0.jar"
$springJar = "D:\ASprintBootServer\target\asprintboot-server-1.0.0-SNAPSHOT.jar"

function Stop-PortListeners {
    param([int[]]$Ports)
    foreach ($port in $Ports) {
        $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        foreach ($c in $conns) {
            $procId = $c.OwningProcess
            if ($procId -and $procId -ne 0) {
                Write-Host "Stopping process on port $port PID=$procId"
                Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            }
        }
    }
    Start-Sleep -Seconds 2
}

function Wait-Health {
    param([string]$Url, [int]$Retries = 30)
    for ($i = 0; $i -lt $Retries; $i++) {
        try {
            $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -eq 200) { return $true }
        } catch {}
        Start-Sleep -Seconds 1
    }
    return $false
}

function Start-ServerProcess {
    param([string]$JarPath)
    if (-not (Test-Path $JarPath)) {
        throw "JAR not found: $JarPath"
    }
    return Start-Process -FilePath "java" -ArgumentList "-jar", $JarPath -PassThru -WindowStyle Hidden
}

if (-not (Test-Path $templateJar)) {
    Write-Host "Building serverTemplate..."
    Push-Location $root
    mvn -q clean package -DskipTests
    Pop-Location
}
if (-not (Test-Path $springJar)) {
    Write-Host "Building ASprintBootServer..."
    Push-Location "D:\ASprintBootServer"
    mvn -q package -DskipTests
    Pop-Location
}

New-Item -ItemType Directory -Force -Path $benchDir | Out-Null
$allPorts = @(8180, 9011, 9012, 17080, 17081, 17082)
Stop-PortListeners -Ports $allPorts

Write-Host ""
Write-Host "========== Isolated bench: serverTemplate =========="
$tplProc = Start-ServerProcess -JarPath $templateJar
if (-not (Wait-Health "http://127.0.0.1:17080/template/health")) {
    Stop-Process -Id $tplProc.Id -Force -ErrorAction SilentlyContinue
    throw "serverTemplate failed to start"
}
$tplJson = Join-Path $benchDir "template.json"
Push-Location $root
py -3 tests\compare_spring_bench.py --server template -c $Concurrency -n $Count --save $tplJson
if ($LASTEXITCODE -ne 0) {
    Stop-Process -Id $tplProc.Id -Force -ErrorAction SilentlyContinue
    Pop-Location
    exit $LASTEXITCODE
}
Pop-Location
Stop-Process -Id $tplProc.Id -Force -ErrorAction SilentlyContinue
Stop-PortListeners -Ports $allPorts
Start-Sleep -Seconds 2

Write-Host ""
Write-Host "========== Isolated bench: ASprintBootServer =========="
$sprProc = Start-ServerProcess -JarPath $springJar
if (-not (Wait-Health "http://127.0.0.1:8180/api/health")) {
    Stop-Process -Id $sprProc.Id -Force -ErrorAction SilentlyContinue
    throw "ASprintBootServer failed to start"
}
$sprJson = Join-Path $benchDir "spring.json"
Push-Location $root
py -3 tests\compare_spring_bench.py --server spring -c $Concurrency -n $Count --save $sprJson
if ($LASTEXITCODE -ne 0) {
    Stop-Process -Id $sprProc.Id -Force -ErrorAction SilentlyContinue
    Pop-Location
    exit $LASTEXITCODE
}
Pop-Location
Stop-Process -Id $sprProc.Id -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "========== Merge comparison report =========="
Push-Location $root
py -3 tests\compare_spring_bench.py --merge $tplJson $sprJson `
    -c $Concurrency -n $Count `
    --title $Title `
    --report $Report
$code = $LASTEXITCODE
Pop-Location
exit $code
