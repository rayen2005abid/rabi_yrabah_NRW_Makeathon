@echo off
setlocal
cd /d "%~dp0frontend"
where npm >nul 2>nul
if errorlevel 1 (
  echo Node.js/npm is required. Install Node.js 20+ and retry.
  pause
  exit /b 1
)
if not exist "node_modules" (
  echo Installing frontend dependencies...
  call npm install
  if errorlevel 1 goto :error
)
echo Frontend starting on http://localhost:5173
call npm run dev
goto :eof
:error
echo Frontend startup failed.
pause
exit /b 1
