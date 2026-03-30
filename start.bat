@echo off
cd /d "%~dp0"

if not exist ".env" (
    echo .env file not found. Please copy .env.example to .env and fill in your token.
    pause
    exit /b 1
)

if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

call venv\Scripts\activate.bat

echo Installing dependencies...
pip install -r requirements.txt --quiet

echo Starting bot...
python bot.py
pause
