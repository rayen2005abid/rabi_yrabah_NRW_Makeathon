@echo off
setlocal
cd /d "%~dp0backend"

rem Simple local mode: always use SQLite. Docker Compose uses PostgreSQL separately.
set DATABASE_URL=sqlite:///./warehouse.db
set CONFIG_DIR=../config
if "%CV_BASE_URL%"=="" set CV_BASE_URL=http://localhost:8100
set EMBEDDED_MODE=mock
set AUTO_SEED_DEMO=true

echo ============================================================
echo Smart Core Warehouse - Backend
 echo Local DB: SQLite ^(backend\warehouse.db^)
echo CV API: %CV_BASE_URL%
echo ============================================================

if not exist ".venv\Scripts\python.exe" (
  echo [1/4] Creating virtual environment...
  where py >nul 2>nul
  if errorlevel 1 (
    python -m venv .venv
  ) else (
    py -3 -m venv .venv
  )
  if errorlevel 1 goto :error

  echo [2/4] Installing backend dependencies from requirements.txt...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  if errorlevel 1 goto :error
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto :error
) else (
  echo [1/4] Virtual environment already exists.
  echo [2/4] Synchronizing backend dependencies...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto :error
)

echo [3/4] Applying database migrations...
".venv\Scripts\python.exe" -m alembic upgrade head
if errorlevel 1 goto :error

echo [4/4] Starting FastAPI...
echo.
echo Backend: http://localhost:8000
echo Health:  http://localhost:8000/health
echo Swagger: http://localhost:8000/docs
echo.
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
if errorlevel 1 goto :error
goto :eof

:error
echo.
echo ============================================================
echo BACKEND STARTUP FAILED
 echo Read the error above. If dependencies are damaged, delete backend\.venv
 echo and run start_backend.bat again.
echo ============================================================
pause
exit /b 1
