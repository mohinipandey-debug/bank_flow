@echo off
echo ============================================
echo   BankFlow Setup - Ventures ^& Stores
echo ============================================
echo.

:: Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Python not found. Installing via winget...
    echo.
    winget install Python.Python.3.11
    echo.
    echo [!] IMPORTANT: Close this window and reopen a fresh terminal,
    echo     then run setup.bat again so Python is on your PATH.
    pause
    exit /b
)

echo [OK] Python found:
python --version
echo.

:: Install required packages
echo [..] Installing required packages (takes 2-3 minutes)...
pip install pandas openpyxl xlrd watchdog streamlit plotly pdfplumber --quiet

echo.
echo [OK] All packages installed.
echo.

:: Create folder structure
echo [..] Creating folder structure...
if not exist "statements\Stores\AXIS-8218"    mkdir "statements\Stores\AXIS-8218"
if not exist "statements\Stores\AXIS-7647"    mkdir "statements\Stores\AXIS-7647"
if not exist "statements\Ventures\AXIS-5623"  mkdir "statements\Ventures\AXIS-5623"
if not exist "statements\Ventures\HDFC-7862"  mkdir "statements\Ventures\HDFC-7862"
if not exist "processed"                       mkdir "processed"
if not exist "data"                            mkdir "data"

echo [OK] Folder structure created.
echo.

:: Initialize the database
echo [..] Initializing database...
python database.py
echo.

echo ============================================
echo   Setup Complete!
echo ============================================
echo.
echo Next steps:
echo   1. Confirm keywords_master.xlsx is in this folder
echo   2. Drop bank statement Excel files into the correct folders:
echo        statements\Stores\AXIS-8218\
echo        statements\Stores\AXIS-7647\
echo        statements\Ventures\AXIS-5623\
echo        statements\Ventures\HDFC-7862\
echo   3. Double-click run.bat to start the system
echo.
pause
