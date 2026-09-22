@echo off
setlocal enabledelayedexpansion
title Game Launcher
color 0A

echo ========================================================
echo                 GAME SETUP AND LAUNCHER
echo ========================================================
echo.

:: Step 1: Check Python
echo [1/5] Checking for Python...

set PYTHON_CMD=
python --version >nul 2>&1
if !errorlevel! equ 0 (
    set PYTHON_CMD=python
) else (
    py --version >nul 2>&1
    if !errorlevel! equ 0 (
        set PYTHON_CMD=py
    )
)

if "!PYTHON_CMD!"=="" (
    echo Python is not installed or not in PATH.
    echo Downloading Python 3.11 directly from python.org...
    curl -# -o python_installer.exe https://www.python.org/ftp/python/3.11.8/python-3.11.8-amd64.exe
    if !errorlevel! neq 0 (
        echo.
        echo ERROR: Failed to download the Python installer. Check your internet connection.
        pause
        exit /b 1
    )
    
    echo Installing Python silently ^(this may take a few minutes^)...
    start /wait python_installer.exe /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_launcher=1
    
    if !errorlevel! neq 0 (
        echo.
        echo ERROR: Python installation failed.
        pause
        exit /b 1
    )
    
    echo Python installed successfully.
    del python_installer.exe
    
    echo Note: Windows environment variables need to refresh.
    echo Trying typical installation paths...
    
    set "PATH=%LOCALAPPDATA%\Programs\Python\Python311\Scripts\;%LOCALAPPDATA%\Programs\Python\Python311\;!PATH!"
    
    python --version >nul 2>&1
    if !errorlevel! equ 0 (
        set PYTHON_CMD=python
    ) else (
        py --version >nul 2>&1
        if !errorlevel! equ 0 (
            set PYTHON_CMD=py
        ) else (
            if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
                set PYTHON_CMD="%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
            ) else (
                echo.
                echo ERROR: Could not locate Python after installation.
                echo Please close this window and run setup.bat again to continue.
                pause
                exit /b 0
            )
        )
    )
)

echo Found Python: !PYTHON_CMD!
echo.

:: Step 2: Upgrade pip
echo [2/5] Upgrading pip to the latest version...
!PYTHON_CMD! -m pip install --upgrade pip --quiet
if !errorlevel! neq 0 (
    echo WARNING: Failed to upgrade pip. Continuing anyway...
) else (
    echo Pip upgraded successfully.
)
echo.

:: Step 3: Check and auto-generate requirements.txt
echo [3/5] Checking for game requirements...
if not exist requirements.txt (
    echo requirements.txt not found.
    echo Scanning project for imports and auto-generating requirements.txt...
    
    :: Install pipreqs to scan imports correctly
    !PYTHON_CMD! -m pip install pipreqs --quiet
    if !errorlevel! neq 0 (
        echo.
        echo ERROR: Failed to install pipreqs for auto-generating requirements.
        pause
        exit /b 1
    )
    
    !PYTHON_CMD! -m pipreqs.pipreqs . --force
    if !errorlevel! neq 0 (
        echo.
        echo ERROR: Failed to scan project and generate requirements.txt.
        pause
        exit /b 1
    )
    echo requirements.txt auto-generated successfully.
) else (
    echo requirements.txt found.
)
echo.

:: Step 4: Install packages
echo [4/5] Installing required packages...
!PYTHON_CMD! -m pip install -r requirements.txt
if !errorlevel! neq 0 (
    echo.
    echo ========================================================
    echo ERROR: Failed to install one or more packages from requirements.txt.
    echo Please check the error message above to see which package failed.
    echo ========================================================
    pause
    exit /b 1
)
echo All required packages are ready.
echo.

:: Step 5: Launch the game
echo [5/5] Launching the game...
set ENTRY_POINT=
if exist main.py set ENTRY_POINT=main.py
if "!ENTRY_POINT!"=="" if exist app.py set ENTRY_POINT=app.py
if "!ENTRY_POINT!"=="" if exist game.py set ENTRY_POINT=game.py

if "!ENTRY_POINT!"=="" (
    echo.
    echo ERROR: Cannot find the main entry point ^(main.py, app.py, or game.py^).
    pause
    exit /b 1
)

echo Starting !ENTRY_POINT!...
echo ========================================================
!PYTHON_CMD! !ENTRY_POINT!

if !errorlevel! neq 0 (
    echo.
    echo ========================================================
    echo ERROR: The game crashed or closed unexpectedly.
    echo ========================================================
    pause
    exit /b 1
)

echo.
echo Game finished successfully.
pause
