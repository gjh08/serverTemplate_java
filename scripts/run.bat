@echo off
setlocal
cd /d "%~dp0.."
if not exist "lib\framework-1.0.0-SNAPSHOT.jar" (
  echo 缺少 lib\framework-1.0.0-SNAPSHOT.jar，请先运行 scripts\prepare-lib.ps1
  exit /b 1
)
call mvn -q clean package
if errorlevel 1 exit /b 1
echo.
echo 启动: java -jar target\server-template-1.0.0.jar
java -jar target\server-template-1.0.0.jar %*
