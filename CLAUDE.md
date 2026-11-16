# DishPlay — repères pour les sessions de travail

## Le projet
- `ios/` : app iPhone DishPlay Scan (SwiftUI, ARKit, Metal). Publiée via TestFlight en modifiant `ios/RELEASE_NOTES.txt` sur `main`.
- `backend/` : calculateur (FastAPI + moteur de reconstruction Python). Tests : `cd backend && .venv/bin/python -m pytest -q`.
- `db/` : modèle de base de données (PostgreSQL) et plan de stockage des fichiers. Voir `db/README.md`.
- `colab/`, `tools/` : essai de reconstruction neuronale et outils.
- Le **site web** (Next.js, menus par restaurant, QR) est dans la branche `main1`, pas dans `main`.

## Règles permanentes
- Répondre à l'utilisateur en français, en langage simple, résultat d'abord.
- Ne jamais annoncer un test ou un résultat qui n'a pas été réellement exécuté ; dire ce qui est vérifié et ce qui ne l'est pas.
- Secrets (jetons, certificats, clés) : jamais dans le dépôt ni dans le chat.
- Pas de pull request sans demande explicite.

## Skills à utiliser (dans `.claude/skills/`, sources dans `SOURCES.md`)
- App iPhone : `swiftui-pro` pour toute lecture ou écriture de SwiftUI ; `ui-review` et `accessibility-audit` avant
  une version ; `liquid-glass`, `typography`, `sf-symbols`, `animation-patterns`, `ux-writing` pour le rendu.
- Site web : `frontend-design` pour le design ; `apple-design`, `animate`, `gestures`, `review-animations` pour le
  mouvement ; `webapp-testing` pour vérifier dans un navigateur.
- Méthode : `systematic-debugging`, `test-driven-development`, `verification-before-completion`.
