@echo off
setlocal
cd /d "%~dp0cv_module_simple_v4_phone_camera\cv_simple_v4"
set CORE_CLASSIFIER_ARTIFACT=artifacts\core_classifier_simple_v4
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m uvicorn api.main:app --host 0.0.0.0 --port 8100
) else (
  python -m uvicorn api.main:app --host 0.0.0.0 --port 8100
)
