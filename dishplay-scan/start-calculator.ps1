# DishPlay Scan calculator — Windows 10/11 (native Python 3.12, no WSL needed).
# Usage (PowerShell):  powershell -ExecutionPolicy Bypass -File .\start-calculator.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "backend")
if (-not (Test-Path ".venv\Scripts\python.exe")) {
  py -3.12 -m venv .venv
  .\.venv\Scripts\python.exe -m pip install --upgrade pip
  .\.venv\Scripts\python.exe -m pip install -r requirements.lock
}
# Allow the iPhone to reach the calculator on the private network only (asks for admin once).
$rule = Get-NetFirewallRule -DisplayName "DishPlay Scan 8765" -ErrorAction SilentlyContinue
if (-not $rule) {
  Write-Host "Adding a Windows Firewall rule for TCP 8765 on Private networks (admin prompt)..."
  Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile -Command New-NetFirewallRule -DisplayName "DishPlay Scan 8765" -Direction Inbound -Protocol TCP -LocalPort 8765 -Action Allow -Profile Private'
}
.\.venv\Scripts\python.exe ..\tools\doctor.py --quick
.\.venv\Scripts\python.exe -m app.main @args
