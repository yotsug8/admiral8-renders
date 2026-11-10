@echo off
setlocal
chcp 65001 >nul
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\start_studio.ps1" %*
if errorlevel 1 (
    echo.
    echo Setup failed. Restart Admiral8.cmd to retry.
    if "%~1"=="" pause
    exit /b 1
)
