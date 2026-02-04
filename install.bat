@echo off
REM OmO Monitor Installation Script for Windows
REM This script automates the installation process for OmO Monitor

echo.
echo OmO Monitor Installation Script for Windows
echo =============================================
echo.

REM Check if we're in the right directory
if not exist "setup.py" (
    echo Error: Please run this script from the omo-monitor root directory
    echo The directory should contain setup.py and omo_monitor\ folder
    exit /b 1
)

if not exist "omo_monitor" (
    echo Error: Please run this script from the omo-monitor root directory
    echo The directory should contain setup.py and omo_monitor\ folder
    exit /b 1
)

echo Found omo_monitor project directory

REM Check Python version
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed or not in PATH
    echo Please install Python 3.7 or higher from https://www.python.org/
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VER=%%i
echo Python version: %PYTHON_VER%

REM Create virtual environment if it doesn't exist
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo Error: Failed to create virtual environment
        exit /b 1
    )
    echo Virtual environment created
) else (
    echo Virtual environment already exists
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

REM Upgrade pip
echo Upgrading pip...
python -m pip install --upgrade pip

REM Install dependencies
echo Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo Error: Failed to install dependencies
    exit /b 1
)

REM Install package in development mode
echo Installing omo-monitor in development mode...
pip install -e .
if errorlevel 1 (
    echo Error: Failed to install omo-monitor
    exit /b 1
)

REM Test installation
echo.
echo Testing installation...
omo-monitor --version
if errorlevel 1 (
    echo.
    echo Warning: omo-monitor command not found in PATH
    echo You can run it directly with:
    echo   venv\Scripts\omo-monitor --help
) else (
    echo omo-monitor command is available
)

echo.
echo =============================================
echo Installation complete!
echo =============================================
echo.
echo Next steps:
echo 1. Activate the virtual environment: venv\Scripts\activate.bat
echo 2. Run 'omo-monitor --help' to see available commands
echo 3. Run 'omo-monitor config show' to view current configuration
echo.
echo For more detailed usage instructions, see MANUAL_TEST_GUIDE.md
echo.

pause
