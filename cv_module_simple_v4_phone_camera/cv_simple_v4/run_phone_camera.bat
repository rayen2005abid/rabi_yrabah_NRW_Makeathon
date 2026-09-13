@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo ERROR: .venv not found. Create/install the Python 3.12 environment first.
  exit /b 1
)
set PHONE_CAMERA_URL=%~1
if "%PHONE_CAMERA_URL%"=="" set PHONE_CAMERA_URL=http://172.10.20.11:4747/video
echo.
echo PHONE CAMERA MODE
echo Source: %PHONE_CAMERA_URL%
echo.
echo Put one core fully inside the green rectangle, hold still, then press SPACE.
".venv\Scripts\python.exe" -m src.simple_camera --artifact artifacts/core_classifier_simple_v4 --config configs/default.yaml --source "%PHONE_CAMERA_URL%" --no-mirror
endlocal
