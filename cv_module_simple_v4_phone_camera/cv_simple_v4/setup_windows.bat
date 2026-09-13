@echo off
setlocal
cd /d "%~dp0"
echo Smart Core Warehouse CV - Windows setup
py -3.12 --version >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python 3.12 was not found.
  echo Install with: winget install -e --id Python.Python.3.12
  exit /b 1
)
if exist .venv rmdir /s /q .venv
py -3.12 -m venv .venv
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -c "import sys,numpy,cv2,torch,torchvision; print('Python',sys.version.split()[0]); print('NumPy',numpy.__version__); print('OpenCV',cv2.__version__); print('Torch',torch.__version__)"
if errorlevel 1 exit /b 1
echo.
echo SETUP COMPLETE
endlocal
