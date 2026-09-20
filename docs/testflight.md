# Installer DishPlay Capture avec TestFlight

DishPlay reste un site web pour les clients et l’espace restaurant. L’app iPhone est son compagnon de capture. La distribution TestFlight utilise un runner Mac GitHub ; aucun SDK Apple n’est installé sur le laptop Linux de 8 Go.

## Version disponible

Le 20 septembre 2026, **0.3.0 (build 5.1)** a passé [le workflow de signature et d’envoi](https://github.com/Omazi/dishplay3d/actions/runs/35536319612), depuis le commit `b03d671`, avec Xcode 26.3 et le SDK iOS 26.2. L’API Apple confirme un build `VALID` et l’état `IN_BETA_TESTING`.

Le build est associé au groupe interne **DishPlay - Tests iPhone** dans [TestFlight](https://appstoreconnect.apple.com/apps/6814221035/testflight/ios). Les consignes sont disponibles en français et en anglais. Les notifications automatiques sont désactivées ; aucun nouveau testeur ni lien public n’a été ajouté. Les testeurs déjà inscrits peuvent ouvrir TestFlight et mettre à jour DishPlay Capture.

Cette version ouvre une caméra simple : **Filmer mon plat → Enregistrer → Arrêter et utiliser la vidéo**. Elle prépare jusqu’à 24 photos et les envoie automatiquement si le plat est associé. Le PC reconstruit le modèle. Le démarrage n’attend plus la reconnaissance du plat ou de la table ; le scan spatial reste une option avancée. Voir [le parcours et ses limites](automatic-scan.md).

## Prérequis du compte

- Une inscription active à l’Apple Developer Program et un accès App Store Connect.
- Les accords Apple à jour, acceptés par le titulaire du compte.
- Une fiche d’app dans App Store Connect, associée au Bundle ID enregistré pour DishPlay. La fiche doit exister avant l’envoi du premier build.
- Une identité **Apple Distribution** avec sa clé privée et un profil **App Store** pour ce Bundle ID exact.
- Une clé API App Store Connect pour l’envoi. La préparation initiale des certificats/profils nécessite une clé d’équipe avec les permissions correspondantes ; une clé individuelle ne donne pas accès aux API de provisioning. Le rôle Admin permet cette préparation et porte sur tout le compte, pas seulement cette app.

Le fichier `.p8` reste local et dans les secrets GitHub. Ne le copiez ni dans une conversation, ni dans le dépôt. Les Key ID, Issuer ID et Team ID sont des identifiants de configuration, distincts du contenu privé de la clé. L’Apple ID et son mot de passe ne sont pas nécessaires à ce pipeline.

## Configuration GitHub

Dépôt : `Omazi/dishplay3d`. Les variables et secrets peuvent être placés dans l’environnement GitHub **testflight** ou au niveau du dépôt.

| Type | Nom | Valeur |
| --- | --- | --- |
| Variable | `APPLE_TEAM_ID` | Team ID de 10 caractères, section Membership du compte Developer |
| Variable | `APPLE_KEY_ID` | Identifiant de la clé API |
| Variable | `APPLE_ISSUER_ID` | Issuer ID de la clé d’équipe |
| Variable | `IOS_BUNDLE_ID` | Identifiant exact enregistré ; valeur par défaut `app.dishplay.capture` |
| Secret | `APP_STORE_CONNECT_API_KEY` | Contenu PEM original du fichier `.p8` |
| Secret | `IOS_DISTRIBUTION_P12_BASE64` | Certificat Apple Distribution et clé privée exportés en PKCS#12, encodés en base64 sur une ligne |
| Secret | `IOS_DISTRIBUTION_P12_PASSWORD` | Mot de passe du PKCS#12 |
| Secret | `IOS_PROVISION_PROFILE_BASE64` | Profil App Store `.mobileprovision`, encodé en base64 sur une ligne |

La création initiale du certificat peut se faire avec une CSR générée sous Linux et les API Apple. Il n’est pas nécessaire de posséder un Mac pour cette préparation. Conservez la clé privée correspondante : télécharger le certificat seul ne suffit pas pour signer. Réutilisez cette identité dans les builds suivants ; le pipeline ne crée ni ne révoque de certificats.

Après cette préparation, une clé d’envoi avec moins de permissions peut remplacer la clé de préparation. Les certificats et profils sont alors déjà fournis au workflow ; il ne fait pas de provisioning automatique. Pour cette version du workflow, gardez une clé d’équipe avec Issuer ID, autorisée à charger le build.

## Fiche d’app Apple

Une fois le Bundle ID enregistré : App Store Connect → Apps → **+** → Nouvelle app.

- Plateforme : iOS.
- Nom proposé : **DishPlay Capture** (adapter si ce nom est indisponible).
- Langue principale : français.
- Bundle ID : exactement la valeur de `IOS_BUNDLE_ID`.
- SKU proposé : `dishplay-capture-ios`.

Aucune soumission à l’App Store public n’est faite par le pipeline. Les déclarations dans App Store Connect doivent correspondre à l’app : envoi volontaire de photos, association à un compte restaurant, aucune publicité ni suivi. Le manifeste du paquet déclare les photos et l’identifiant d’association liés au compte pour le fonctionnement de l’app, ainsi que la lecture de métadonnées de fichiers du conteneur (`C617.1`). TLS, Keychain et SHA-256 utilisent les API du système Apple.

## Lancer le build

Actions → **iOS TestFlight** → **Run workflow**, branche **main**.

- `upload=true` : signature, export, validation Apple et envoi dans App Store Connect.
- `upload=false` : même archive signée et export IPA, sans envoi à Apple.

Le workflow n’expose les secrets qu’au job de distribution lancé manuellement depuis `main`. Il vérifie d’abord une archive Release non signée avec Xcode 26.3 et le SDK iOS 26. Le déploiement minimum reste iOS 17, sous réserve des capacités matérielles vérifiées à l’exécution.

Avant la signature, le script rejette un profil expirant, un autre Team ID, un autre Bundle ID, un profil développement/Ad Hoc/Enterprise et un certificat sans clé privée correspondante. Le numéro de build `run_number.run_attempt` change à chaque exécution ou nouvelle tentative.

Seuls l’IPA et les symboles de débogage sont conservés en artefact privé pendant sept jours. La clé API, le PKCS#12 et les profils temporaires ne sont pas inclus dans cet artefact. Le trousseau temporaire et les profils installés par le job sont retirés à sa fin.

## Sur l’iPhone

Le traitement Apple est terminé et le build est associé au groupe interne. Si tu as déjà installé l’app, ouvre TestFlight et touche **Mettre à jour**. Pour une première installation :

1. Installer [TestFlight](https://apps.apple.com/app/testflight/id899247664) sur l’iPhone.
2. Ouvrir [DishPlay Capture → TestFlight](https://appstoreconnect.apple.com/apps/6814221035/testflight/ios), puis **Tests internes → DishPlay - Tests iPhone**.
3. Dans **Testeurs**, cliquer sur **+ / Inviter des testeurs**, sélectionner son propre compte App Store Connect et l’ajouter.
4. Ouvrir l’invitation sur l’iPhone, l’accepter dans TestFlight et installer **DishPlay Capture 0.3.0 (5.1)**. [Procédure Apple](https://developer.apple.com/help/app-store-connect/test-a-beta-version/add-internal-testers).

Pour les prochains envois, vérifier la fin du traitement Apple, compléter les informations éventuellement demandées et ajouter le nouveau build au groupe interne. Le workflow signe et envoie l’app ; il ne gère pas l’affectation des builds aux groupes.

Le succès de `altool --upload-app` signifie que le transfert a réussi. Il ne garantit pas la fin du traitement Apple, la disponibilité du build pour le testeur ou une capture réussie sur le téléphone. Le pipeline n’envoie pas d’invitations et ne crée pas de lien public de bêta. Pour des testeurs externes, Apple impose un parcours de revue distinct.

## Limites et vérifications restantes

L’archive Release, les ressources embarquées, la signature, l’export IPA, la validation Apple, l’envoi et le traitement TestFlight sont vérifiés pour le build 5.1. Les essais physiques de cette nouvelle capture restent à effectuer. Un artefact non signé ne s’installe pas directement sur iPhone.

Les tests sur Mac encodent et décodent de vraies vidéos : orientation, sélection limitée, rejet des vidéos immobiles/sombres/trop courtes, conservation des originaux et protection des photos déjà sauvegardées. Après installation, vérifier sur iPhone : permissions, démarrage et arrêt caméra, orientation, petits écrans, interruption, import vidéo, reprise de la préparation, association au plat, transfert, attente du PC, résultat USDZ et fidélité du plat. Ces essais sur appareil réel ne sont pas remplacés par la compilation cloud.

## Références officielles

- [Exigences SDK depuis le 28 avril 2026](https://developer.apple.com/news/?id=ueeok6yw).
- [Clés API App Store Connect](https://developer.apple.com/help/app-store-connect/get-started/app-store-connect-api).
- [Créer la fiche d’app](https://developer.apple.com/help/app-store-connect/create-an-app-record/add-a-new-app).
- [Envoi des builds et traitement Apple](https://developer.apple.com/help/app-store-connect/manage-builds/upload-builds).
- [Certificats de signature sur les runners GitHub](https://docs.github.com/en/actions/how-tos/deploy/deploy-to-third-party-platforms/sign-xcode-applications).
- [Raisons des API de métadonnées de fichiers](https://developer.apple.com/documentation/bundleresources/app-privacy-configuration/nsprivacyaccessedapitypes/nsprivacyaccessedapitypereasons).
