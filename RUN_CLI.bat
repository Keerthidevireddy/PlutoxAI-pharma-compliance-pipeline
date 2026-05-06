@echo off
REM Quick launcher for CLI mode
echo Activating virtual environment...
call .venv\Scripts\activate.bat

echo.
echo Running pipeline...
python main.py "extract-call.pdf"

echo.
pause
