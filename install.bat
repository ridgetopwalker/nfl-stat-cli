@echo off
REM ============================================================================
REM pro-football-slm : Run-Once Windows Installer Bootstrapper
REM Installs Python (if needed), pip (if needed), all required packages,
REM and sets up pro-football-slm.
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
