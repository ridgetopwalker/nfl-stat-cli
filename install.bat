@echo off
REM ============================================================================
REM nfl-stat-cli : Run-Once Windows Installer Bootstrapper
REM Installs Python (if needed), pip (if needed), all required packages,
REM and sets up nfl-stat-cli.
REM ============================================================================
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] Installer encountered an issue ^(exit code %ERRORLEVEL%^).
    pause
    exit /b %ERRORLEVEL%
)
echo.
endlocal
