@echo off
setlocal
if defined PYTHONPATH (set "PYTHONPATH=%~dp0;%PYTHONPATH%") else (set "PYTHONPATH=%~dp0")
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -m pro_football_slm %*
) else (
    where py >nul 2>nul
    if errorlevel 1 (
        python -m pro_football_slm %*
    ) else (
        py -3 -m pro_football_slm %*
    )
)
