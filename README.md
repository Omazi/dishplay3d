# DishPlay Scan — prototype P1

Boîte AR réglable sur iPhone + reconstruction **progressive réelle** sur un ordinateur local : nuage coloré puis
surface partielle affichés dans le bas de l'écran **pendant** la capture ; finition texturée après « Terminer ».
Sans LiDAR obligatoire, sans Mac, sans moteur payant. L’ancien code (site Next.js, app DishPlay Capture 0.x, worker) est conservé intact dans la branche `main1`.

```
iPhone (ARKit poses + images, boîte RealityKit, aperçu Metal)
   │ HTTPS épinglé : PUT vues (DPF1)        ▲ WebSocket événements + géométrie versionnée (DPG1)
   ▼                                        │
Calculateur Windows/Linux : FastAPI ── processus de reconstruction
   paires temporelles → vérif. pose (SIFT+RANSAC) → rectification → StereoSGBM + contrôle G/D
   → confirmation par plusieurs vues indépendantes → fusion TSDF (Open3D)
   → nuage + maillage étayé (classes mesuré / interpolé)
   → « Terminer » : re-stéréo plus fine, maillage maître, texture, GLB/PLY + rapport
```

| Dossier | Contenu |
|---|---|
| `backend/` | calculateur (`app/`), moteur (`reconstruction/`), tests (`tests/`), `requirements.lock` |
| `ios/` | app SwiftUI (`App/ Scanner/ Preview/ Network/ Storage/`), paquet testable `ScanCore/`, `project.yml` |
| `contracts/` | schémas JSON versionnés (capture, messages) ; formats binaires décrits dans `backend/reconstruction/preview_format.py` |
| `tools/` | `replay_session.py`, `pack_session.py` (zip compact d'une session), `bench_quality.py` (banc de qualité), `doctor.py`, `verify_capture.py`, `render_geometry.py`, `asc_profile.py`, `asc_testflight.py`, `scan_client.py` |
| `docs/` | `SETUP_WINDOWS_LINUX.md`, `TESTFLIGHT.md`, `FIRST_TEST.md`, `TEST_REPORT.md` |
| `compliance/` | `components.csv`, `THIRD_PARTY_NOTICES.md` |

Démarrage rapide : `./start-calculator.sh` (Linux) ou `start-calculator.ps1` (Windows), puis `docs/FIRST_TEST.md`.
Au démarrage, le script installe les bibliothèques manquantes et télécharge une fois le modèle de profondeur
optionnel (99 Mo, Apache-2.0) qui sert à combler les surfaces unies ou brillantes ; `DISHPLAY_MONO=0` pour s'en passer.
Ce modèle tourne en parallèle du reste, pendant le scan et à la finition ; pendant le scan il ne fait jamais attendre
une vue et se met en retrait seul si le PC ne suit pas (`DISHPLAY_MONO_LIVE=0` pour le réserver à la finition).
Tests : `cd backend && .venv/bin/python -m pytest -q` ; Swift : `cd ios/ScanCore && swift test` (macOS / CI).

Conventions : mètres ; `T_A_from_B` ; matrices sérialisées ligne par ligne ; repère objet = boîte (origine au
centre de la base, +y vers le haut) ; caméra CV = caméra AR × diag(1,−1,−1,1). Une réinitialisation du suivi ARKit
crée une nouvelle époque : jamais de fusion entre époques ; une révision de boîte reconstruit le volume.

État réel : voir `docs/TEST_REPORT.md` — compilé et testé automatiquement, **pas encore essayé sur iPhone**.
