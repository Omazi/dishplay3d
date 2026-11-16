# Calculateur DishPlay Scan — installation Windows / Linux

Le calculateur est le PC qui reconstruit le plat pendant que l'iPhone filme. Aucun GPU, aucun Mac et aucune
licence payante ne sont nécessaires. Mesuré ici : Linux x86-64, 4 cœurs, sans GPU (voir `TEST_REPORT.md`).

## Prérequis
- Python **3.12** (Windows : installateur python.org, cocher « Add to PATH » ; Linux : `python3.12` + `python3.12-venv`).
- ~1,5 Go d'espace pour l'environnement Python (Open3D tire des dépendances lourdes), + ~100–300 Mo par session.
- iPhone et PC sur **le même Wi‑Fi**, sans « isolation des clients » (souvent active sur les réseaux invités).
- 8 Go de RAM conseillés (pic mesuré à confirmer sur votre PC : `tools/doctor.py`).

## Windows (recommandé : Python natif, sans WSL)
```powershell
git clone https://github.com/Omazi/dishplay3d.git
cd dishplay3d
powershell -ExecutionPolicy Bypass -File .\start-calculator.ps1
```
Le premier lancement crée `backend\.venv`, installe `requirements.lock`, ajoute (une fois, avec demande admin)
une règle de pare-feu TCP 8765 limitée au profil **Privé**, lance le diagnostic puis le serveur.
Le réseau Wi‑Fi doit être déclaré « Privé » dans Windows (Paramètres › Réseau › Propriétés).

**WSL2** : en mode NAT par défaut, l'iPhone ne peut pas joindre le serveur. Utiliser Python natif (ci‑dessus) ou
activer `networkingMode=mirrored` dans `%UserProfile%\.wslconfig` (Windows 11 22H2+), puis `./start-calculator.sh`.

## Linux
```bash
git clone https://github.com/Omazi/dishplay3d.git && cd dishplay3d
./start-calculator.sh            # options : --port 8765 --data ~/dishplay-scan-data
```
Pare-feu (ufw) : `sudo ufw allow from 192.168.0.0/16 to any port 8765 proto tcp`.

## Ce que le serveur affiche au démarrage
- l'adresse `https://<IP-du-PC>:8765`, le **code de jumelage** (6 chiffres, renouvelé à chaque démarrage),
- l'**empreinte TLS** SHA‑256 du certificat auto-signé (créé dans `~/dishplay-scan-data/tls`, réutilisé ensuite),
- un QR code (dans le terminal et sur `https://127.0.0.1:8765/`, page accessible seulement depuis le PC).
  Le navigateur du PC avertira que le certificat est auto-signé : c'est attendu, l'iPhone vérifie l'empreinte.

## Diagnostic
```bash
backend/.venv/bin/python tools/doctor.py          # Windows : backend\.venv\Scripts\python.exe tools\doctor.py
```
Vérifie versions OpenCV/Open3D, RAM, adresse LAN, port libre, WSL, et exécute un auto-test **synthétique** de la
chaîne (preuve que les bibliothèques fonctionnent sur ce PC, jamais présenté comme un scan).

## Données
`~/dishplay-scan-data/sessions/<id>/` : `frames/` (JPEG originaux + JSON + profondeur LiDAR éventuelle),
`preview/vNNNNN.dpg` (toutes les versions intermédiaires), `final/` (PLY, GLB, texture, rapport, manifeste),
`dishplay-scan.sqlite3` (index). Rejouer une session : voir `FIRST_TEST.md` § 9.

## Sécurité
HTTPS uniquement (certificat épinglé par l'app), jeton par appareil après jumelage, limite de taille des
requêtes (20 Mo), noms de fichiers d'artefacts contrôlés, une session active. Ne pas exposer le port 8765 sur
Internet (pas de redirection de port sur la box). `--insecure-http` n'existe que pour des tests automatisés ;
l'app iOS refuse le HTTP.
