# 打分发 zip：serverTemplate/ + lib/framework JAR + 已构建 fat jar
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$jar = Join-Path $root "target\server-template-1.0.0.jar"
if (-not (Test-Path $jar)) {
    Write-Host "请先 mvn clean package"
    exit 1
}
$outDir = Join-Path $root "dist"
$zip = Join-Path $outDir "server-template-1.0.0.zip"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$stage = Join-Path $env:TEMP "server-template-dist"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $stage | Out-Null
$exclude = @('target', 'dist', '.idea')
Get-ChildItem $root -Force | Where-Object { $exclude -notcontains $_.Name } | ForEach-Object {
    Copy-Item $_.FullName (Join-Path $stage $_.Name) -Recurse -Force
}
Copy-Item $jar (Join-Path $stage "server-template-1.0.0.jar") -Force
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zip
Remove-Item $stage -Recurse -Force
Write-Host "已生成 -> $zip"
