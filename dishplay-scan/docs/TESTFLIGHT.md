# Compilation et TestFlight sans Mac

Tout passe par GitHub Actions (runner macOS hébergé) et l'API App Store Connect. Rien n'est à faire sur un Mac.

## 1. Vérification automatique (aucun secret)
Le workflow **DishPlay Scan — checks** (`.github/workflows/ios-check.yml`) se lance à chaque push touchant
`dishplay-scan/` : tests Python (Linux), tests `ScanCore` (`swift test`), génération du projet par XcodeGen 2.46.0
(SHA‑256 vérifié) et compilation **non signée** pour iPhone, avec contrôle du bundle (metallib, manifeste de
confidentialité, `NSLocalNetworkUsageDescription`). Résultat réel : voir `TEST_REPORT.md`.

## 2. Réutilisation de la configuration Apple existante
Le dépôt a déjà publié DishPlay Capture 0.6.0 sur TestFlight avec ces paramètres GitHub (environnement
`testflight` ou dépôt) — ils sont réutilisés tels quels :

| Type | Nom |
| --- | --- |
| Variable | `APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_ISSUER_ID` |
| Secret | `APP_STORE_CONNECT_API_KEY` (texte du .p8), `IOS_DISTRIBUTION_P12_BASE64`, `IOS_DISTRIBUTION_P12_PASSWORD` |

DishPlay Scan est une **nouvelle app** (`app.dishplay.scan`), l'ancienne `app.dishplay.capture` n'est pas touchée.
Le certificat Apple Distribution est commun à l'équipe ; seul un **profil App Store** propre au nouvel identifiant
est nécessaire. Le workflow le crée/réutilise automatiquement via l'API (`tools/asc_profile.py`) si la clé API a le
rôle **Admin** (gestion des identifiants et profils). Sinon : exécuter ce script depuis Windows/Linux avec une clé
Admin, puis enregistrer le fichier en secret `SCAN_PROVISION_PROFILE_BASE64` (`base64 -w0 profile.mobileprovision`).

## 3. Une seule étape manuelle dans App Store Connect (navigateur)
Apple ne permet pas de créer la fiche d'app par API. Une fois (après le premier passage du workflow qui enregistre
l'identifiant, ou après `tools/asc_profile.py`) :
App Store Connect › Apps › **+** › Nouvelle app › iOS, nom **DishPlay Scan**, langue français, Bundle ID
**app.dishplay.scan**, SKU `dishplay-scan-ios`. Sans cette fiche, l'envoi échoue avec une erreur explicite d'Apple.

## 4. Lancer le build TestFlight
GitHub › Actions › **DishPlay Scan — TestFlight** › Run workflow (branche contenant le code) › `upload = true`.
Le job réexécute les vérifications, crée/réutilise le profil, installe la signature dans un trousseau temporaire
(script existant `scripts/apple/install-signing.py`, qui refuse un profil d'un autre Team/Bundle ou non App Store),
archive, exporte l'IPA, la valide puis l'envoie (`altool`), et nettoie le trousseau. Numéro de build :
`run_number.run_attempt`.

## 5. Sur l'iPhone
App Store Connect › DishPlay Scan › TestFlight › Tests internes : créer un groupe, s'y ajouter, ajouter le build
une fois « Prêt à tester » (traitement Apple : de quelques minutes à une heure). Installer depuis l'app TestFlight.

## Limites honnêtes
- Ce workflow de distribution **n'a pas été exécuté** dans cette livraison : il nécessite vos secrets et la fiche
  d'app. Le précédent pipeline équivalent (mêmes scripts de signature) avait réussi pour 0.6.0.
- Un historique du dépôt mentionne un refus de démarrage de job macOS pour plafond de dépenses GitHub ; si cela se
  reproduit, il faut ajuster la facturation Actions ou attendre la remise à zéro mensuelle.
- La compilation et les tests sur runner ne valident ni la caméra, ni le suivi AR, ni la qualité : seul l'essai sur
  iPhone (`FIRST_TEST.md`) le fait.
