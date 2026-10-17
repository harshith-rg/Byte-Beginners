@echo off
setlocal
cd /d "%~dp0"

echo ===================================================
echo   Byte-Beginners / PathVoice Navigation Assistant
echo ===================================================
echo.

REM Activate Python virtual environment if found
if exist ".venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call .venv\Scripts\activate.bat
) else if exist "..\.venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call ..\.venv\Scripts\activate.bat
)

echo Starting PathVoice server at http://localhost:8000 ...
echo (Backend API + Frontend Web App are served together)
echo.

cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
