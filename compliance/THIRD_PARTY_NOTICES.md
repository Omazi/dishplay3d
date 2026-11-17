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
| ONNX Runtime (onnxruntime) | 1.31.1 | MIT | exécution du modèle de profondeur sur processeur |
| Depth Anything V2 **Small** (poids ONNX, téléchargés au démarrage, hors dépôt) | export onnx-community | Apache-2.0 | comble les surfaces unies ou brillantes |
Dépendances d'Open3D (dash, plotly, flask, matplotlib, pandas, scikit-learn, ipywidgets…) : licences permissives
(MIT/BSD/PSF/MPL-2.0 pour certifi et tqdm) ; requises à l'import d'Open3D, non utilisées par DishPlay.

Outils de build (non distribués) : XcodeGen 2.46.0 (MIT), Xcode (Apple).

## Décisions
- **Règle du propriétaire (17 novembre) : licences permissives uniquement** (MIT, BSD, Apache-2.0 ou équivalent). Rien
  sous GPL/AGPL, rien de « non commercial », rien avec partage à l'identique ou condition de vente.
- Écartés pour cette raison : OpenMVS (AGPL-3.0) ; les variantes Base/Large/Giant de Depth Anything V2
  (CC BY-NC) — seule la variante Small (Apache-2.0) est utilisée.
- Compatibles, non intégrés au calculateur livré : COLMAP / pycolmap (BSD-3, essai de positions à partir des photos),
  gsplat (Apache-2.0) et PyTorch (BSD-3) pour l'étape neuronale optionnelle sur carte graphique.
- Aucun moteur 3D payant. Pas d'Object Capture d'Apple (réservé aux iPhone Pro).
- À remplacer avant toute vente, côté site web (branche `main1`) : le modèle 3D de burger de démonstration
  (Ehsan Abbasi, CC BY-SA 4.0, partage à l'identique).
- Tolérés car ni modifiés ni redistribués : certifi et tqdm (MPL-2.0), tirés par Open3D.
- Point ouvert : la roue opencv-python embarque FFmpeg (LGPL). Usage local, sans redistribution par DishPlay : sans
  objet pour P1. Si le calculateur est un jour redistribué en binaire, construire OpenCV minimal sans videoio
  (modules core, imgproc, imgcodecs, features2d, calib3d) et sans nonfree.
- Cet inventaire repose sur les métadonnées déclarées par les paquets ; ce n'est pas un avis juridique.

## Skills de développement (`.claude/skills/`)

Fichiers d'instructions pour l'assistant de développement, non distribués avec l'app ni avec le calculateur.
Sources, révisions et licences : `.claude/skills/SOURCES.md` (MIT : twostraws/SwiftUI-Agent-Skill,
rshankras/claude-code-apple-skills, emilkowalski/skills, obra/superpowers ; Apache-2.0 : anthropics/skills).
