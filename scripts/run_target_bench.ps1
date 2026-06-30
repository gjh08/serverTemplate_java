# Target bench: WS@1000 and TCP@2000 only (isolated)
param(
    [int]$Count = 10000
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$benchDir = Join-Path $root "bench_data"
$templateJar = Join-Path $root "target\server-template-1.0.0.jar"
$springJar = "D:\ASprintBootServer\target\asprintboot-server-1.0.0-SNAPSHOT.jar"
$allPorts = @(8180, 9011, 9012, 17080, 17081, 17082)
$Concurrency = "1000,2000"
$Slots = "WS:1000,TCP:2000"

function Stop-PortListeners {
    param([int[]]$Ports)
    foreach ($port in $Ports) {
        Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
            ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    }
    Start-Sleep -Seconds 3
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

function Start-ServerProcess {
    param([string]$JarPath)
    $jvmArgs = @("-Xms512m", "-Xmx1g", "-XX:+UseG1GC", "-jar", $JarPath)
    return Start-Process -FilePath "java" -ArgumentList $jvmArgs -PassThru -WindowStyle Hidden
}

Stop-PortListeners -Ports $allPorts
New-Item -ItemType Directory -Force -Path $benchDir | Out-Null

Write-Host ">>> serverTemplate (pooling build)"
$tplProc = Start-ServerProcess -JarPath $templateJar
if (-not (Wait-Health "http://127.0.0.1:17080/template/health")) {
    Stop-Process -Id $tplProc.Id -Force -ErrorAction SilentlyContinue
    throw "serverTemplate start failed"
}
Push-Location $root
$tplJson = Join-Path $benchDir "pool_template.json"
py -3 tests\compare_spring_bench.py --server template -c $Concurrency -n $Count --save $tplJson
if ($LASTEXITCODE -ne 0) { throw "template bench failed" }
Stop-Process -Id $tplProc.Id -Force -ErrorAction SilentlyContinue
Pop-Location
Stop-PortListeners -Ports $allPorts

Write-Host ">>> ASprintBootServer"
$sprProc = Start-ServerProcess -JarPath $springJar
if (-not (Wait-Health "http://127.0.0.1:8180/api/health")) {
    Stop-Process -Id $sprProc.Id -Force -ErrorAction SilentlyContinue
    throw "spring start failed"
}
Push-Location $root
$sprJson = Join-Path $benchDir "pool_spring.json"
py -3 tests\compare_spring_bench.py --server spring -c $Concurrency -n $Count --save $sprJson
if ($LASTEXITCODE -ne 0) { throw "spring bench failed" }
Stop-Process -Id $sprProc.Id -Force -ErrorAction SilentlyContinue
Pop-Location

Write-Host ">>> merge evaluate slots: $Slots"
Push-Location $root
py -3 tests\compare_spring_bench.py --merge $tplJson $sprJson `
    -c $Concurrency -n $Count `
    --title "pool-pushmessage-target" `
    --report bench_pool_target.md `
    --require-slots $Slots
$code = $LASTEXITCODE
Pop-Location
exit $code
