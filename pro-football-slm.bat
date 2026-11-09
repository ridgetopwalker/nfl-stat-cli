@echo off
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0pro_football_slm.py" %*
) else (
    where py >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        py -3 "%~dp0pro_football_slm.py" %*
    ) else (
        python "%~dp0pro_football_slm.py" %*
    )
)
