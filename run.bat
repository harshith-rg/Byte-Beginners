@echo off
setlocal
cd /d "%~dp0"

if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0track.py" %*
) else if exist "C:\Users\ANISH P\AppData\Local\Programs\Python\Python314\python.exe" (
    "C:\Users\ANISH P\AppData\Local\Programs\Python\Python314\python.exe" "%~dp0track.py" %*
) else (
    py "%~dp0track.py" %*
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Execution finished with error code %ERRORLEVEL%.
    pause
)
