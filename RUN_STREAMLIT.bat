@echo off
REM Quick launcher for Streamlit UI
echo Activating virtual environment...
call .venv\Scripts\activate.bat

echo.
echo Launching Streamlit UI...
echo Browser will open at http://localhost:8501
echo.
echo Press Ctrl+C to stop the server
streamlit run streamlit_app.py

pause
