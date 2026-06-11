@echo off
echo ============================================
echo   BankFlow - Starting System
echo ============================================
echo.

:: Start the folder watcher in a minimised background window
echo [..] Starting folder watcher...
start /min "BankFlow Watcher" python watcher.py

:: Brief pause so watcher initialises before we scan
timeout /t 2 /nobreak >nul

:: Process any statements already sitting in the folders
echo [..] Processing existing statement files...
python processor.py --scan-all

echo.
echo [..] Starting dashboard...
echo [OK] Opening at http://localhost:8501
echo.
echo     Press Ctrl+C in this window to stop the system.
echo.
streamlit run dashboard.py --server.headless true --browser.serverAddress localhost
