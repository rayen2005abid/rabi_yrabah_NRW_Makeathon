$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

Write-Host "Smart Core Warehouse CV - Windows setup" -ForegroundColor Cyan
Write-Host "Looking for a supported Python version (3.11, 3.12, or 3.13)..."

$preferredVersions = @("3.12", "3.13", "3.11")
$selectedVersion = $null

foreach ($version in $preferredVersions) {
    try {
        & py "-$version" -c "import sys; print(sys.version)" *> $null
        if ($LASTEXITCODE -eq 0) {
            $selectedVersion = $version
            break
        }
    }
    catch {
        # Try the next supported version.
    }
}

if (-not $selectedVersion) {
    Write-Host "" 
    Write-Host "No supported Python runtime was found." -ForegroundColor Red
    Write-Host "Python 3.14 is intentionally not used for this project on Windows because the current OpenCV/NumPy stack may install an experimental NumPy build." -ForegroundColor Yellow
    Write-Host "" 
    Write-Host "Install Python 3.12 with:" -ForegroundColor Yellow
    Write-Host "  winget install -e --id Python.Python.3.12"
    Write-Host "" 
    Write-Host "Then close and reopen PowerShell and run:" -ForegroundColor Yellow
    Write-Host "  .\setup_windows.ps1"
    exit 1
}

Write-Host "Using Python $selectedVersion" -ForegroundColor Green

if (Test-Path ".venv") {
    Write-Host "Removing existing .venv..."
    Remove-Item -Recurse -Force ".venv"
}

& py "-$selectedVersion" -m venv .venv

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

Write-Host "Upgrading pip..."
& $python -m pip install --upgrade pip

Write-Host "Installing project dependencies..."
& $python -m pip install -r requirements.txt

Write-Host "Running environment smoke check..."
& $python -c "import sys, numpy, cv2, torch, torchvision; print('Python:', sys.version.split()[0]); print('NumPy:', numpy.__version__); print('OpenCV:', cv2.__version__); print('PyTorch:', torch.__version__); print('torchvision:', torchvision.__version__)"

Write-Host "" 
Write-Host "SETUP COMPLETE" -ForegroundColor Green
Write-Host "Use the virtual-environment Python directly, for example:"
Write-Host "  .\.venv\Scripts\python.exe -m src.inspect_dataset --config configs/default.yaml"
Write-Host "  .\.venv\Scripts\python.exe -m src.train --config configs/default.yaml"
Write-Host "  .\.venv\Scripts\python.exe -m src.live_camera --artifact artifacts/core_classifier_v2"
