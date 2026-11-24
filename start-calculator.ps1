# DishPlay Scan calculator - Windows 10/11 (native Python 3.12, no WSL needed).
# Usage: double-click Demarrer-le-calculateur.cmd, or in PowerShell:
#   powershell -ExecutionPolicy Bypass -File .\start-calculator.ps1 [-SetupOnly] [options of the calculator]
# -SetupOnly : install everything, open the firewall, run the checks, then stop WITHOUT starting the calculator.
#              Exit code 0 when every step worked. The automatic check on a Windows machine uses it.
# Options of the calculator (passed on as they are): --port 8765 --data <folder> --new-certificate --forget-devices
# This file is plain ASCII on purpose: Windows PowerShell 5.1 reads a file without BOM as ANSI, and an accent in
# a message would come out garbled.
param([switch]$SetupOnly)
$ErrorActionPreference = "Stop"
$problems = 0
Set-Location (Join-Path $PSScriptRoot "backend")

function Test-Python312([string]$exe, [string[]]$prefix) {
  if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { return $false }
  $previous = $ErrorActionPreference
  $ErrorActionPreference = "Continue"     # what a program writes on its error output must not stop the script
  $version = & $exe @prefix -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
  $code = $LASTEXITCODE
  $ErrorActionPreference = $previous
  return ($code -eq 0 -and "$version".Trim() -eq "3.12")
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
  # The python.org installer brings the "py" launcher; other installations only have "python".
  $python = $null
  $pythonArgs = @()
  if (Test-Python312 "py" @("-3.12")) { $python = "py"; $pythonArgs = @("-3.12") }
  elseif (Test-Python312 "python" @()) { $python = "python" }
  elseif (Test-Python312 "python3" @()) { $python = "python3" }
  if (-not $python) {
    Write-Host "Python 3.12 est introuvable sur ce PC."
    Write-Host "Installez-le depuis https://www.python.org/downloads/windows/ (version 3.12, en cochant 'Add python.exe to PATH'),"
    Write-Host "puis relancez ce script."
    exit 1
  }
  Write-Host "Creation de l'environnement Python du calculateur..."
  & $python @pythonArgs -m venv .venv
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "L'environnement Python n'a pas pu etre cree (voir le message ci-dessus)."
    exit 1
  }
  .\.venv\Scripts\python.exe -m pip install --upgrade pip
}

# Install the libraries again whenever the list changed (after an update of the project).
$lock = (Get-FileHash requirements.lock -Algorithm SHA256).Hash
$stamp = ".venv\requirements.sha256"
if (-not (Test-Path $stamp) -or ((Get-Content $stamp -Raw).Trim() -ne $lock)) {
  Write-Host "Installation des bibliotheques du calculateur (plusieurs minutes la premiere fois)..."
  .\.venv\Scripts\python.exe -m pip install -r requirements.lock
  if ($LASTEXITCODE -eq 0) { Set-Content -Path $stamp -Value $lock -NoNewline }
  else {
    $problems++
    Write-Host "Certaines bibliotheques n'ont pas pu etre installees (pas d'internet ?). Demarrage avec ce qui est la ; nouvel essai au prochain lancement."
  }
}

# Optional depth model for uniform or shiny dishes (about 99 MB, once). Set DISHPLAY_MONO=0 to skip it.
if ($env:DISHPLAY_MONO -ne "0") {
  $ErrorActionPreference = "Continue"
  .\.venv\Scripts\python.exe ..\tools\get_models.py
  $ErrorActionPreference = "Stop"
}

# Let the iPhone reach the calculator, on private networks only. Windows asks for the administrator's consent
# once: the rule is then there for good. A refusal must not stop the calculator.
$ruleName = "DishPlay Scan 8765"
function Test-FirewallRule { return [bool](Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue) }
if (-not (Test-FirewallRule)) {
  Write-Host "Ouverture du pare-feu Windows pour l'iPhone (port 8765, reseaux prives) : Windows va demander votre accord."
  # The command travels encoded: passed as plain text, the quotes around the rule's name were lost on the way
  # and the rule was never created (Windows then asked again at every start).
  $command = "New-NetFirewallRule -DisplayName '$ruleName' -Direction Inbound -Protocol TCP -LocalPort 8765 -Action Allow -Profile Private | Out-Null"
  $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
  try {
    Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList "-NoProfile", "-EncodedCommand", $encoded
  } catch {
    Write-Host "L'accord n'a pas ete donne : $($_.Exception.Message)"
  }
  if (Test-FirewallRule) { Write-Host "Pare-feu : regle ajoutee." }
  else {
    $problems++
    Write-Host "ATTENTION : la regle du pare-feu n'a pas ete ajoutee. L'iPhone ne pourra peut-etre pas joindre le calculateur."
    Write-Host "  Relancez ce script en acceptant la demande de Windows, ou ajoutez la regle a la main :"
    Write-Host "  pare-feu Windows > regles de trafic entrant > nouveau port TCP 8765, reseau prive."
  }
}

.\.venv\Scripts\python.exe ..\tools\doctor.py --quick
if ($LASTEXITCODE -ne 0) { $problems++ }

if ($SetupOnly) {
  if ($problems -eq 0) { Write-Host "Preparation terminee : tout est en place."; exit 0 }
  Write-Host "Preparation terminee avec $problems probleme(s) : voir les messages ci-dessus."
  exit 1
}
.\.venv\Scripts\python.exe -m app.main @args
exit $LASTEXITCODE
