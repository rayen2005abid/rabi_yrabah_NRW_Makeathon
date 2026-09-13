@echo off
setlocal
cd /d "%~dp0cv_module_simple_v3\cv_module"
set CORE_CLASSIFIER_ARTIFACT=artifacts\core_classifier_simple_v3
echo ============================================================
echo SOPALTEC CV v3 API
echo ============================================================
echo CV API: http://localhost:8100
echo Artifact: %CORE_CLASSIFIER_ARTIFACT%
echo.
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m uvicorn api.main:app --host 0.0.0.0 --port 8100
) else (
  python -m uvicorn api.main:app --host 0.0.0.0 --port 8100
)
