@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo SOPAL TEC - Smart Core Warehouse Demo
echo ============================================================
echo Starting CV API, backend, frontend, and site camera integration.
echo The backend auto-seeds a fresh database automatically.
echo.
set CV_BASE_URL=http://localhost:8100
start "SOPAL CV v3 API" cmd /k call "%~dp0..\..\start_cv_v3.bat"
timeout /t 5 /nobreak >nul
start "SOPAL WCS Backend" cmd /k call "%~dp0start_backend.bat"
timeout /t 3 /nobreak >nul
start "SOPAL WCS Frontend" cmd /k call "%~dp0start_frontend.bat"
echo.
echo Frontend: http://localhost:5173
echo Backend:  http://localhost:8000
echo CV API:   http://localhost:8100
echo Swagger:  http://localhost:8000/docs
echo.
echo The Factory Console camera sends frames to CV automatically.
echo You can close this window. The service windows stay open.
timeout /t 5 >nul
start "" http://localhost:5173
