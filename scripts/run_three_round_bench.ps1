# 3-round isolated benchmark: template must win all protocol x concurrency slots each round
param(
    [string]$Concurrency = "100,400,1000,2000",
    [int]$Count = 10000,
    [int]$Rounds = 3
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$benchDir = Join-Path $root "bench_data"
$templateJar = Join-Path $root "target\server-template-1.0.0.jar"
$springJar = "D:\ASprintBootServer\target\asprintboot-server-1.0.0-SNAPSHOT.jar"
$allPorts = @(8180, 9011, 9012, 17080, 17081, 17082)

function Stop-PortListeners {
    param([int[]]$Ports)
    foreach ($port in $Ports) {
        $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        foreach ($c in $conns) {
            $procId = $c.OwningProcess
            if ($procId -and $procId -ne 0) {
                Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            }
        }
    }
    Start-Sleep -Seconds 2
}

function Wait-Health {
    param([string]$Url, [int]$Retries = 40)
    for ($i = 0; $i -lt $Retries; $i++) {
        try {
            $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -eq 200) { return $true }
        } catch {}
        Start-Sleep -Seconds 1
    }
    return $false
}

function Assert-ServerAlive {
    param([System.Diagnostics.Process]$Proc, [string]$HealthUrl, [string]$Label)
    if ($Proc.HasExited) {
        throw ($Label + " crashed exit=" + $Proc.ExitCode)
    }
    if (-not (Wait-Health $HealthUrl 3)) {
        throw ($Label + " health check failed after bench")
    }
}

function Start-ServerProcess {
    param([string]$JarPath)
    if (-not (Test-Path $JarPath)) { throw ("JAR not found: " + $JarPath) }
    $jvmArgs = @("-Xms512m", "-Xmx1g", "-XX:+UseG1GC", "-jar", $JarPath)
    return Start-Process -FilePath "java" -ArgumentList $jvmArgs -PassThru -WindowStyle Hidden
}

New-Item -ItemType Directory -Force -Path $benchDir | Out-Null
$roundResults = @()

for ($round = 1; $round -le $Rounds; $round++) {
    Write-Host ""
    Write-Host "============================================================"
    Write-Host ("Round " + $round + " / " + $Rounds + " isolated benchmark")
    Write-Host "============================================================"

    Stop-PortListeners -Ports $allPorts
    Start-Sleep -Seconds 5

    $tplJson = Join-Path $benchDir ("round" + $round + "_template.json")
    $sprJson = Join-Path $benchDir ("round" + $round + "_spring.json")
    $report = Join-Path $root ("bench_round" + $round + ".md")

    Write-Host ">>> serverTemplate"
    $tplProc = Start-ServerProcess -JarPath $templateJar
    if (-not (Wait-Health "http://127.0.0.1:17080/template/health")) {
        Stop-Process -Id $tplProc.Id -Force -ErrorAction SilentlyContinue
        throw ("serverTemplate start failed round=" + $round)
    }
    Push-Location $root
    py -3 tests\compare_spring_bench.py --server template -c $Concurrency -n $Count --save $tplJson
    if ($LASTEXITCODE -ne 0) {
        Stop-Process -Id $tplProc.Id -Force -ErrorAction SilentlyContinue
        Pop-Location
        throw ("template bench failed round=" + $round + " exit=" + $LASTEXITCODE)
    }
    Assert-ServerAlive -Proc $tplProc -HealthUrl "http://127.0.0.1:17080/template/health" -Label "serverTemplate"
    Stop-Process -Id $tplProc.Id -Force -ErrorAction SilentlyContinue
    Pop-Location
    Stop-PortListeners -Ports $allPorts

    Write-Host ">>> ASprintBootServer"
    $sprProc = Start-ServerProcess -JarPath $springJar
    if (-not (Wait-Health "http://127.0.0.1:8180/api/health")) {
        Stop-Process -Id $sprProc.Id -Force -ErrorAction SilentlyContinue
        throw ("ASprintBootServer start failed round=" + $round)
    }
    Push-Location $root
    py -3 tests\compare_spring_bench.py --server spring -c $Concurrency -n $Count --save $sprJson
    if ($LASTEXITCODE -ne 0) {
        Stop-Process -Id $sprProc.Id -Force -ErrorAction SilentlyContinue
        Pop-Location
        throw ("spring bench failed round=" + $round + " exit=" + $LASTEXITCODE)
    }
    Assert-ServerAlive -Proc $sprProc -HealthUrl "http://127.0.0.1:8180/api/health" -Label "ASprintBootServer"
    Stop-Process -Id $sprProc.Id -Force -ErrorAction SilentlyContinue
    Pop-Location

    Write-Host ">>> merge and evaluate"
    Push-Location $root
    $title = "round-" + $round + "-isolated"
    py -3 tests\compare_spring_bench.py --merge $tplJson $sprJson `
        -c $Concurrency -n $Count `
        --title $title `
        --report $report `
        --require-template-win
    $code = $LASTEXITCODE
    Pop-Location

    if ($code -eq 0) {
        $roundResults += [PSCustomObject]@{ Round = $round; Pass = $true; Report = $report }
        Write-Host ("PASS round " + $round)
    } else {
        $roundResults += [PSCustomObject]@{ Round = $round; Pass = $false; Report = $report }
        Write-Host ("FAIL round " + $round + " exit=" + $code)
        Write-Host "Stopping: all 3 rounds must pass for full win."
        $roundResults | Format-Table -AutoSize
        exit $code
    }

    Start-Sleep -Seconds 3
}

Write-Host ""
Write-Host "============================================================"
Write-Host "ALL 3 ROUNDS PASSED - serverTemplate wins every slot"
Write-Host "============================================================"
$roundResults | Format-Table -AutoSize
exit 0
