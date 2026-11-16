# Compilation et TestFlight sans Mac

Tout passe par GitHub Actions (runner macOS hébergé) et l'API App Store Connect. Rien n'est à faire sur un Mac.

## 1. Vérification automatique (aucun secret)
Le workflow **DishPlay Scan — checks** (`.github/workflows/ios-check.yml`) se lance à chaque push touchant
tout push : tests Python (Linux), tests `ScanCore` (`swift test`), génération du projet par XcodeGen 2.46.0
(SHA‑256 vérifié) et compilation **non signée** pour iPhone, avec contrôle du bundle (metallib, manifeste de
confidentialité, `NSLocalNetworkUsageDescription`). Résultat réel : voir `TEST_REPORT.md`.

## 2. Fiche et signature : celles qui existent déjà
DishPlay Scan est publiée comme **nouvelle version (1.0.0) de la fiche existante « DishPlay Capture »**
(App Store Connect ID `6814221035`, bundle `app.dishplay.capture`, équipe `XQGND2V48C`), qui a déjà reçu les builds
0.1.0 à 0.6.0 par GitHub Actions. Aucune nouvelle fiche, aucun nouvel identifiant, aucun nouveau profil :
le workflow réutilise les paramètres déjà configurés dans l'environnement GitHub `testflight` (ou le dépôt) :

| Type | Nom |
| --- | --- |
| Variable | `APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_ISSUER_ID`, `IOS_BUNDLE_ID` (défaut `app.dishplay.capture`) |
| Secret | `APP_STORE_CONNECT_API_KEY`, `IOS_DISTRIBUTION_P12_BASE64`, `IOS_DISTRIBUTION_P12_PASSWORD`, `IOS_PROVISION_PROFILE_BASE64` |

Le script de signature repris des builds 0.x (`ios/ci/install-signing.py`, inchangé) refuse un profil expiré, d'une autre équipe, d'un
autre bundle ou non « App Store ». Si le profil a expiré, `tools/asc_profile.py` (Windows/Linux, clé API Admin) en
recrée un pour `app.dishplay.capture` ; le workflow l'appelle automatiquement si le secret de profil est absent.

Conséquence sur l'iPhone : la mise à jour TestFlight **remplace** l'app DishPlay Capture 0.6 par DishPlay Scan
(même bundle). Les anciens builds restent consultables dans App Store Connect ; l’ancien code reste dans la branche
`main1` (dossier `native/ios/`).

## 3. Lancer le build TestFlight
Deux façons de lancer la publication depuis `main` :
- modifier `ios/RELEASE_NOTES.txt` (notes de version) et pousser sur `main` : le workflow démarre et envoie le build ;
- ou Actions › **DishPlay Scan — TestFlight** › Run workflow › `main` › `upload = true`.
Le job réexécute les vérifications, installe la signature dans un trousseau temporaire, archive, exporte l'IPA, la
valide puis l'envoie (`altool`), et nettoie le trousseau. Numéro de build : `run_number.run_attempt` (version 1.0.0,
supérieure à 0.6.x).

## 4. Sur l'iPhone
Une fois le build « Prêt à tester » (traitement Apple : quelques minutes à une heure), l'ajouter au groupe interne
existant **DishPlay - Tests iPhone** ([TestFlight](https://appstoreconnect.apple.com/apps/6814221035/testflight/ios)),
puis ouvrir TestFlight sur l'iPhone et toucher **Mettre à jour**. Le nom affiché sous l'icône sera « DishPlay Scan ».

## Premier essai d'envoi (16 nov. 2026)
Run [43795707664](https://github.com/Omazi/dishplay3d/actions/runs/43795707664) : tests, compilation, archive **signée**
avec le profil existant `app.dishplay.capture` et export de l'IPA (647 Ko) réussis. **Envoi refusé par Apple** :
`Failed to determine the Apple ID from Bundle ID 'app.dishplay.capture' … A required agreement is missing or has expired`.
Le titulaire du compte doit accepter le contrat Apple mis à jour (developer.apple.com › Account, et App Store Connect ›
Accords). Puis modifier `ios/RELEASE_NOTES.txt` sur `main` pour relancer. Le workflow échoue désormais explicitement
dans ce cas (altool terminait sans code d'erreur).

## Limites honnêtes
- Ce workflow de distribution **n'a pas été exécuté** dans cette livraison : il tourne avec vos secrets depuis `main`. Le précédent pipeline équivalent (mêmes scripts de signature) avait réussi pour 0.6.0.
- Un historique du dépôt mentionne un refus de démarrage de job macOS pour plafond de dépenses GitHub ; si cela se
  reproduit, il faut ajuster la facturation Actions ou attendre la remise à zéro mensuelle.
- La compilation et les tests sur runner ne valident ni la caméra, ni le suivi AR, ni la qualité : seul l'essai sur
  iPhone (`FIRST_TEST.md`) le fait.
