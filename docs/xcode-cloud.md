# DishPlay Capture — préparation Xcode Cloud

## État réel

Le dépôt est préparé, mais **Xcode Cloud n’est pas encore activé**. La lecture autorisée de `GET /v1/ciProducts?filter[app]=6814221035` a renvoyé une liste vide. L’utilisateur dispose uniquement d’un PC Linux. Apple demande de configurer le premier workflow dans Xcode sur un Mac ; l’API permet ensuite de gérer les workflows d’un produit existant. Aucun build Xcode Cloud n’a donc été lancé, aucun forfait payant ni machine louée n’a été ajouté.

L’abonnement Apple Developer inclut 25 heures de calcul mensuel Xcode Cloud. L’accès au Mac n’est nécessaire que pour cette première activation et les éventuels essais locaux ; les builds suivants se déroulent chez Apple. Le code reste dans le dépôt privé `Omazi/dishplay3d`.

## Préparation incluse

- `native/ios/DishPlayCapture.xcodeproj` et son schéma partagé `DishPlayCapture`, avec la cible d’app et la cible de tests d’interface.
- Signature automatique pour l’équipe `XQGND2V48C`, bundle `app.dishplay.capture`, version `0.6.1`.
- `native/ios/ci_scripts/ci_post_clone.sh` télécharge XcodeGen **2.46.0**, vérifie son SHA-256, régénère le projet à partir de `project.yml` et exécute les contrôles natifs séquentiellement. Aucune installation Homebrew ni accès administrateur.
- `scripts/apple/verify-native.sh` conserve les contrôles existants : couverture, démarrage caméra, reçus persistants, encodage vidéo réel, extraction des vues, silhouette, cube, masque et garde-fous de signature. Le premier échec arrête le script.
- `ci_post_xcodebuild.sh` refuse un résultat de compilation en échec et vérifie les ressources du paquet après l’archive. Le validateur est un lien symbolique vers le script commun ; Xcode Cloud prend en charge ces ressources liées pour les phases suivantes.
- Les déclenchements automatiques iOS de GitHub Actions sont retirés. Ses workflows manuels restent disponibles comme solution de secours. Le pipeline web/Vercel est distinct.

Le projet partagé d’amorçage a été produit sous Linux avec Xcodeproj 1.27.0 ; il n’a pas encore été ouvert ou compilé dans Xcode. Le fichier `project.yml` reste la référence : XcodeGen régénère le projet et le schéma avant chaque action cloud. Sur un Mac, après une modification structurelle, régénérer et committer le projet partagé pour garder l’ouverture locale à jour.

## Première activation sur un Mac

Prévoir Xcode 26.3 ou une version stable plus récente compatible avec le Mac, et le compte Apple ayant accès à l’équipe DishPlay. Aucune compilation n’est à lancer sur le laptop Linux.

1. Cloner le dépôt privé avec son propre accès GitHub, puis ouvrir le projet :

   ```sh
   git clone https://github.com/Omazi/dishplay3d.git
   cd dishplay3d
   open native/ios/DishPlayCapture.xcodeproj
   ```

2. Dans Xcode, sélectionner le schéma **DishPlayCapture**, se connecter au compte Apple Developer et vérifier l’équipe et le Bundle ID. Choisir **Product → Xcode Cloud → Create Workflow**. Apple peut afficher un accord à lire et accepter par le titulaire du compte.
3. Autoriser l’accès Xcode Cloud au seul dépôt **Omazi/dishplay3d**. Confirmer la fiche existante **DishPlay Capture**, App Store Connect ID `6814221035` ; ne pas créer une autre app.
4. Configurer le workflow ci-dessous, retirer toute post-action de notification email/Slack, puis lancer le premier build. Après cette activation, les workflows et leurs résultats se gèrent depuis l’onglet Xcode Cloud d’App Store Connect ou son API.

## Réglages du workflow

| Réglage | Valeur prévue |
| --- | --- |
| Nom | DishPlay Capture — TestFlight |
| Projet | `native/ios/DishPlayCapture.xcodeproj` |
| Schéma | `DishPlayCapture` |
| Branche | `main` |
| Premier lancement | Manuel, pour vérifier l’installation et les journaux |
| Déclenchement ensuite | Changements sur `main`, limités à `native/ios/` et `scripts/apple/` |
| Xcode / macOS | Xcode 26.3 si proposé, sinon stable plus récent ; macOS compatible, au moins 15 |
| Test | Debug, `DishPlayCaptureUITests`, un seul simulateur iPhone ; iPhone 13 si proposé |
| Tests requis | Un échec doit empêcher la distribution TestFlight |
| Archive | Release, iOS, **TestFlight (Internal Testing Only)** |
| Signature | Automatique, gérée par Apple |
| Numéro de build | Laisser Xcode Cloud le gérer ; `0.6.1 (1)` est distinct du précédent `0.6.0 (10.1)` |
| Distribution | Groupe existant **DishPlay - Tests iPhone**, après réussite des contrôles et traitement Apple |
| Notifications | Aucune post-action email/Slack ; ne pas ajouter de testeurs ni de lien public |

Ne copier ni la clé `.p8`, ni le certificat `.p12`, ni la connexion de base de données dans le dépôt ou les variables Xcode Cloud. Le code natif ne nécessite aucun secret du site pour être compilé. La signature cloud utilise l’équipe Apple connectée.

Après l’archive, vérifier le build réel dans TestFlight et l’état Apple `VALID`. Avant son association au groupe interne, désactiver `autoNotifyEnabled`, puis contrôler `IN_BETA_TESTING`. La post-action de distribution interne peut être configurée après validation de ces réglages ; le premier envoi peut être associé manuellement ou via l’API existante. Ne pas annoncer une version installable sur la seule base d’un script ou d’une archive non signée.

## Contrôles effectués depuis Linux

- Lecture du projet avec Xcodeproj : les 20 fichiers Swift de l’app et le fichier des tests d’interface sont référencés, sans source manquante ; Bundle ID, équipe, ressources localisées, schéma et archive Release cohérents.
- Syntaxe Bash vérifiée pour les scripts ; les tests natifs sont repris du workflow Mac précédent, sans lancer de compilateur local.
- Validation du script post-archive sur le vrai paquet non signé `0.6.1 (1)` issu du workflow GitHub `35548134345` : succès avec le paquet complet, refus d’une compilation échouée et d’un paquet privé de manifeste de confidentialité, passage sans validation d’archive pour une action de test.
- Les captures UI utilisent désormais l’écran complet et attendent la disposition paysage avant de contrôler les boutons. Ce changement attend sa prochaine exécution sur Mac.

Ces vérifications **ne remplacent pas** le premier build Xcode Cloud, sa signature, son traitement TestFlight, ni l’essai de la vraie caméra sur iPhone 13. La dernière version installable reste **0.6.0 (10.1)**.

## Sources Apple

- [Configurer le premier workflow dans Xcode](https://developer.apple.com/documentation/xcode/configuring-your-first-xcode-cloud-workflow).
- [Préparer le projet et partager les schémas](https://developer.apple.com/documentation/xcode/setting-up-your-project-to-use-xcode-cloud).
- [Scripts et ressources liés](https://developer.apple.com/documentation/xcode/writing-custom-build-scripts).
- [Distribution TestFlight](https://developer.apple.com/documentation/xcode/distributing-your-xcode-cloud-builds-through-testflight).
- [Numérotation des builds](https://developer.apple.com/documentation/xcode/setting-the-next-build-number-for-xcode-cloud-builds).
- [Quota inclus](https://developer.apple.com/xcode-cloud/).
