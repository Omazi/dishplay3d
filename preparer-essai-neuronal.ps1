# Prepare le dernier scan termine pour l'essai de reconstruction neuronale (Gaussian splatting).
# Usage : clic droit > Executer avec PowerShell, ou   .\preparer-essai-neuronal.ps1
# La fenetre reste ouverte a la fin, pour lire ou se trouve le fichier a envoyer.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "backend")
if (-not (Test-Path ".venv\Scripts\python.exe")) {
  Write-Host "Lancez d'abord start-calculator.ps1 une fois."
  Read-Host "Appuyez sur Entree pour fermer"
  exit 1
}
.\.venv\Scripts\python.exe ..\tools\export_splat_dataset.py --zip @args
$code = $LASTEXITCODE
Write-Host ""
if ($code -ne 0) {
  Write-Host "La preparation a echoue : voir le message ci-dessus."
} else {
  Write-Host "Envoyez dans le carnet Colab le fichier splat_dataset.zip indique ci-dessus, a la ligne 'Zip:' (voir docs\ESSAI_NEURONAL.md)."
}
Read-Host "Appuyez sur Entree pour fermer"
exit $code
