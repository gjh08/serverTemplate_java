# 复制 framework JAR 到 lib/ 并安装到本地 Maven 仓库
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$candidates = @(
    (Join-Path $root "..\framework\target\framework-1.0.0-SNAPSHOT.jar"),
    (Join-Path $root "..\Agent_java\framework\target\framework-1.0.0-SNAPSHOT.jar"),
    "D:\Agent_java\framework\target\framework-1.0.0-SNAPSHOT.jar"
)
$src = $null
foreach ($c in $candidates) {
    if (Test-Path $c) { $src = (Resolve-Path $c).Path; break }
}
$dst = Join-Path $root "lib\framework-1.0.0-SNAPSHOT.jar"
if ($src) {
    Copy-Item $src $dst -Force
    Write-Host "已复制 -> $dst"
} elseif (-not (Test-Path $dst)) {
    Write-Host "未找到 framework JAR。请先构建主工程，或将 framework-1.0.0-SNAPSHOT.jar 放入 lib/"
    exit 1
} else {
    Write-Host "使用已有 -> $dst"
}
mvn -f (Join-Path $root "pom.xml") -q install:install-file `
    "-Dfile=$dst" `
    "-DgroupId=serverdll" `
    "-DartifactId=framework" `
    "-Dversion=1.0.0-SNAPSHOT" `
    "-Dpackaging=jar"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "已安装到本地 Maven 仓库: serverdll:framework:1.0.0-SNAPSHOT"
