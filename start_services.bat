@echo off
REM ============================================
REM Polymarket Wallet Analysis - Start Services
REM ============================================

echo Starting Polymarket Wallet Analysis Services...
echo.

REM Verificar que existe el venv
if not exist "venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found at venv\Scripts\activate.bat
    echo Please create it with: python -m venv venv
    pause
    exit /b 1
)

REM Iniciar Django en una nueva ventana (con venv activado)
echo Starting Django server on http://localhost:8000 ...
start "Django Server" cmd /k "cd /d %~dp0 && venv\Scripts\activate.bat && python manage.py runserver 0.0.0.0:8000"

REM Esperar un momento antes de iniciar Celery
timeout /t 3 /nobreak > nul

REM Iniciar Celery worker en otra ventana (con venv activado)
echo Starting Celery worker...
start "Celery Worker" cmd /k "cd /d %~dp0 && venv\Scripts\activate.bat && celery -A polymarket_project worker --loglevel=info --pool=solo"

echo.
echo ============================================
echo Services started in separate windows:
echo   - Django Server: http://localhost:8000
echo   - Celery Worker: Processing background tasks
echo ============================================
echo.
echo Press any key to exit this window...
pause > nul
