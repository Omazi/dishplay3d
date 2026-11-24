@echo off
rem Double-cliquez sur ce fichier pour demarrer le calculateur DishPlay Scan.
rem La fenetre reste ouverte a la fin, pour lire un eventuel message d erreur.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-calculator.ps1" %*
echo.
echo Le calculateur est arrete. Appuyez sur une touche pour fermer cette fenetre.
pause >nul
