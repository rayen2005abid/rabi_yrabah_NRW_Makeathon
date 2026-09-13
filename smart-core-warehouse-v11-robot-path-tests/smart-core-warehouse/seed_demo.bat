@echo off
setlocal
cd /d "%~dp0backend"
set DATABASE_URL=sqlite:///./warehouse.db
set CONFIG_DIR=../config
set EMBEDDED_MODE=mock
if not exist ".venv\Scripts\python.exe" (
  echo Backend environment not installed. Run start_backend.bat once first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m alembic upgrade head
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m app.demo.seed
if errorlevel 1 goto :error
echo Demo data seeded successfully.
pause
goto :eof
:error
echo Demo seed failed.
pause
exit /b 1
