@echo off
REM ============================================
REM Polymarket Wallet Analysis - Stop Services
REM ============================================

echo Stopping Polymarket Wallet Analysis Services...
echo.

REM Matar procesos de Django (runserver)
echo Stopping Django server...
taskkill /f /im python.exe /fi "WINDOWTITLE eq Django Server*" 2>nul
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
    taskkill /f /pid %%a 2>nul
)

REM Matar procesos de Celery
echo Stopping Celery worker...
taskkill /f /im celery.exe 2>nul
taskkill /f /im python.exe /fi "WINDOWTITLE eq Celery Worker*" 2>nul

echo.
echo Services stopped.
pause
