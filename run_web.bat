@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    py -3 -m venv .venv
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
echo.
echo Starting Local AI at http://127.0.0.1:8000
".venv\Scripts\python.exe" -m uvicorn webapp:app --host 127.0.0.1 --port 8000
pause
