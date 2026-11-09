@echo off
setlocal
set "PYTHONPATH=%~dp0;%PYTHONPATH%"
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -m nfl_stat_cli %*
) else (
    where py >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        py -3 -m nfl_stat_cli %*
    ) else (
        python -m nfl_stat_cli %*
    )
)
