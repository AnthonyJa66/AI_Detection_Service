@echo off
setlocal
title Smart Video Monitoring Launcher

set "PROJECT_DIR=E:\_Work\CodexProjects\Test1"
set "APP_URL=http://127.0.0.1:5000"

echo ========================================
echo Smart Video Monitoring System
echo ========================================
echo.

if not exist "%PROJECT_DIR%\app.py" (
    echo [ERROR] app.py not found:
    echo %PROJECT_DIR%\app.py
    pause
    exit /b 1
)

echo Project directory: %PROJECT_DIR%
echo.
echo Starting Flask server...
start "Flask Server" /D "%PROJECT_DIR%" cmd /k python app.py

echo Waiting for server startup...
timeout /t 5 /nobreak >nul

echo Opening browser...
start "" "%APP_URL%"

echo.
echo Startup commands have been executed.
echo If the page does not open, check the Flask Server window.
pause
endlocal