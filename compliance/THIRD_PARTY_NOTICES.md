# Mentions tierces — DishPlay Scan P1

Inventaire complet (versions installées, licence déclarée dans les métadonnées, usage, décision) :
`components.csv`, généré depuis l'environnement réellement installé (`backend/requirements.lock`, Python 3.12).

## App iOS
Aucune bibliothèque tierce embarquée : frameworks Apple (SwiftUI, ARKit, RealityKit, Metal/MetalKit, CryptoKit,
Security) soumis au contrat Apple Developer Program, et le paquet local `ScanCore` (code du projet).

## Calculateur (non distribué avec l'app ; exécuté sur le PC de l'utilisateur)
| Composant | Version | Licence | Rôle |
|---|---|---|---|
| OpenCV (opencv-python-headless) | 4.12.0.88 | Apache-2.0 | SIFT, RANSAC/essentielle, rectification, StereoSGBM, triangulation |
| FFmpeg (embarqué dans la roue OpenCV) | celle de la roue | LGPL-2.1+ | non utilisé par le code (images JPEG seulement) |
| Open3D | 0.19.0 | MIT | TSDF, maillage, UV atlas, projection de texture |
| FastAPI / Starlette / Uvicorn / websockets | 0.121.2 / 0.49.3 / 0.38.0 / 15.0.1 | MIT / BSD-3 / BSD-3 / BSD-3 | API HTTP/WS |
| NumPy / SciPy | 2.2.6 / 1.18.1 | BSD-3 | calcul |
| cryptography | 46.0.3 | Apache-2.0 OR BSD-3 | certificat TLS local, JWT App Store Connect |
| segno | 1.6.6 | BSD-3 | QR code de jumelage |
| jsonschema | 4.26.0 | MIT | validation des contrats |
Dépendances d'Open3D (dash, plotly, flask, matplotlib, pandas, scikit-learn, ipywidgets…) : licences permissives
(MIT/BSD/PSF/MPL-2.0 pour certifi et tqdm) ; requises à l'import d'Open3D, non utilisées par DishPlay.

Outils de build (non distribués) : XcodeGen 2.46.0 (MIT), Xcode (Apple).

## Décisions
- Aucun moteur 3D payant, aucune licence non commerciale, aucun poids IA (la complétion est une interface
  désactivée). Pas de COLMAP/OpenMVS/Object Capture.
- Point ouvert : la roue opencv-python embarque FFmpeg (LGPL). Usage local, sans redistribution par DishPlay : sans
  objet pour P1. Si le calculateur est un jour redistribué en binaire, construire OpenCV minimal sans videoio
  (modules core, imgproc, imgcodecs, features2d, calib3d) et sans nonfree.
- Cet inventaire repose sur les métadonnées déclarées par les paquets ; ce n'est pas un avis juridique.

## Skills de développement (`.claude/skills/`)

Fichiers d'instructions pour l'assistant de développement, non distribués avec l'app ni avec le calculateur.
Sources, révisions et licences : `.claude/skills/SOURCES.md` (MIT : twostraws/SwiftUI-Agent-Skill,
rshankras/claude-code-apple-skills, emilkowalski/skills, obra/superpowers ; Apache-2.0 : anthropics/skills).
