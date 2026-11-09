@echo off
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0nfl_stat_cli.py" %*
) else (
    where py >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        py -3 "%~dp0nfl_stat_cli.py" %*
    ) else (
        python "%~dp0nfl_stat_cli.py" %*
    )
)
