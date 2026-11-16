# Prepare le dernier scan pour l'essai de reconstruction neuronale (Gaussian splatting).
# Usage : clic droit > Executer avec PowerShell, ou   .\preparer-essai-neuronal.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "backend")
if (-not (Test-Path ".venv\Scripts\python.exe")) { Write-Host "Lance d'abord start-calculator.ps1 une fois."; exit 1 }
.\.venv\Scripts\python.exe ..\tools\export_splat_dataset.py --zip @args
Write-Host ""
Write-Host "Ouvre le dossier indique ci-dessus dans Brush (voir docs\ESSAI_NEURONAL.md)."
