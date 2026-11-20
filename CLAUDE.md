# DishPlay — repères pour les sessions de travail

## Le projet
- `ios/` : app iPhone DishPlay Scan (SwiftUI, ARKit, Metal). Publiée via TestFlight en modifiant `ios/RELEASE_NOTES.txt` sur `main`.
  Son apparence tient dans `ios/App/DesignSystem/` (couleurs par rôle, styles de texte, boutons, verre) ; les valeurs
  des couleurs, clair et sombre, sont dans une seule table : `tools/ios_colors.py` (l'exécuter après modification,
  `--check` pour vérifier). Identité : celle du site (papier, encre, bleu), une seule couleur d'action.
- `backend/` : calculateur (FastAPI + moteur de reconstruction Python). Tests : `cd backend && .venv/bin/python -m pytest -q`.
- `db/` : modèle de base de données (PostgreSQL) et plan de stockage des fichiers. Voir `db/README.md`.
- `colab/`, `tools/` : essai de reconstruction neuronale et outils.
- Le **site web** (Next.js, menus par restaurant, QR) est dans la branche `main1`, pas dans `main`.

## Règles permanentes
- Répondre à l'utilisateur en français, en langage simple, résultat d'abord.
- Ne jamais annoncer un test ou un résultat qui n'a pas été réellement exécuté ; dire ce qui est vérifié et ce qui ne l'est pas.
- Secrets (jetons, certificats, clés) : jamais dans le dépôt ni dans le chat.
- Pas de pull request sans demande explicite.
- Licences : uniquement des composants à licence permissive (MIT, BSD, Apache-2.0 ou équivalent). Rien sous GPL ou AGPL,
  rien de « non commercial », rien avec partage à l'identique (CC BY-SA) ni condition de vente. Vérifier la licence
  avant d'ajouter une dépendance, un modèle d'IA ou une ressource, et tenir `compliance/THIRD_PARTY_NOTICES.md` à jour.

## Skills à utiliser (dans `.claude/skills/`, sources dans `SOURCES.md`)
- App iPhone : `swiftui-pro` pour toute lecture ou écriture de SwiftUI ; `ui-review` et `accessibility-audit` avant
  une version ; `liquid-glass`, `typography`, `sf-symbols`, `animation-patterns`, `ux-writing` pour le rendu.
- Site web : `frontend-design` pour le design ; `apple-design`, `animate`, `gestures`, `review-animations` pour le
  mouvement ; `webapp-testing` pour vérifier dans un navigateur.
- Méthode : `systematic-debugging`, `test-driven-development`, `verification-before-completion`.
