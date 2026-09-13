param(
  [Parameter(Mandatory=$true)][string]$Source
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw ".venv not found. Create/install the Python 3.12 environment first."
}
& $python -m src.simple_camera --artifact artifacts/core_classifier_simple_v4 --config configs/default.yaml --source $Source --no-mirror
