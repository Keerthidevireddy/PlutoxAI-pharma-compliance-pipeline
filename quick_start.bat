@echo off
REM ═══════════════════════════════════════════════════════════════════════
REM  Pharma Compliance Pipeline - Quick Start Script (Windows)
REM ═══════════════════════════════════════════════════════════════════════

echo.
echo ┌─────────────────────────────────────────────────────────────────────┐
echo │  Pharma Compliance Pipeline - Automated Setup                       │
echo └─────────────────────────────────────────────────────────────────────┘
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+ from python.org
    pause
    exit /b 1
)

echo [1/5] Checking Python version...
python --version

REM Check if virtual environment exists
if not exist ".venv\" (
    echo.
    echo [2/5] Creating virtual environment...
    python -m venv .venv
) else (
    echo.
    echo [2/5] Virtual environment already exists.
)

REM Activate virtual environment
echo.
echo [3/5] Activating virtual environment...
call .venv\Scripts\activate.bat

REM Install dependencies
echo.
echo [4/5] Installing dependencies...
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

REM Check if .env exists
if not exist ".env" (
    echo.
    echo [5/5] Setting up environment file...
    copy .env.example .env >nul
    echo.
    echo ┌─────────────────────────────────────────────────────────────────────┐
    echo │  IMPORTANT: Please edit .env file and add your Anthropic API key    │
    echo │  Get your key at: https://console.anthropic.com/settings/keys       │
    echo └─────────────────────────────────────────────────────────────────────┘
    echo.
    echo Opening .env file in notepad...
    timeout /t 2 >nul
    notepad .env
) else (
    echo.
    echo [5/5] .env file already exists.
)

echo.
echo ═══════════════════════════════════════════════════════════════════════
echo  Setup Complete! You can now run the pipeline.
echo ═══════════════════════════════════════════════════════════════════════
echo.
echo  CLI Mode:
echo    python main.py "extract-call.pdf"
echo.
echo  Web UI Mode:
echo    streamlit run streamlit_app.py
echo.
echo ═══════════════════════════════════════════════════════════════════════
echo.

pause
