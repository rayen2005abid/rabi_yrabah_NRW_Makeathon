$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$model = Join-Path $PSScriptRoot "artifacts\core_classifier_v2\model.pt"
if (-not (Test-Path $python)) {
    Write-Host "Virtual environment not found. Create Python 3.12 .venv first." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $model)) {
    Write-Host "Trained V2 model not found: artifacts\core_classifier_v2\model.pt" -ForegroundColor Red
    Write-Host "Train it first with:"
    Write-Host "  .\.venv\Scripts\python.exe -m src.train --config configs/default.yaml"
    exit 1
}
& $python -m src.live_camera --artifact artifacts/core_classifier_v2 @args
