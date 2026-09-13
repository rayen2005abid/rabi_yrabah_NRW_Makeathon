@echo off
setlocal
cd /d "%~dp0cv_module_simple_v4_phone_camera\cv_simple_v4"
set PHONE_CAMERA_URL=%~1
if "%PHONE_CAMERA_URL%"=="" set PHONE_CAMERA_URL=http://172.10.20.11:4747/video
echo ============================================================
echo SOPALTEC phone camera connection test
echo ============================================================
echo Source: %PHONE_CAMERA_URL%
echo.
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m src.check_video_source --source "%PHONE_CAMERA_URL%" --show
) else (
  python -m src.check_video_source --source "%PHONE_CAMERA_URL%" --show
)
