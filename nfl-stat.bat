@echo off
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0nfl_stat_cli.py" %*
) else (
    python "%~dp0nfl_stat_cli.py" %*
)
