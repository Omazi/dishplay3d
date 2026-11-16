# Essai de reconstruction neuronale sur votre PC (GTX 1650)

But : voir, sur un de VOS plats, ce que donne une reconstruction par « Gaussian splatting » à partir des
mêmes images que le scan actuel. C'est un essai manuel, pas encore intégré à l'app.

État honnête : l'export du jeu de données est testé (test automatique + vérification sur une vraie capture
iPhone). L'entraînement lui-même n'a **pas** été exécuté par moi : il faut une carte graphique, je n'en ai pas.

## Étapes

1. Mettre le calculateur à jour : `git pull`, relancer `start-calculator.ps1`.
2. Scanner un plat avec l'app, aller jusqu'à **Terminer** et attendre « Modèle prêt ».
3. Sur le PC, dans le dossier du projet : clic droit sur `preparer-essai-neuronal.ps1` → *Exécuter avec PowerShell*.
   Il affiche le dossier créé (`...\sessions\<id>\splat_dataset`) et un zip.
4. Télécharger **Brush** (libre, gratuit, un seul programme, pas d'installation) :
   <https://github.com/ArthurBrussee/brush/releases> → fichier Windows → dézipper.
5. Lancer `brush_app.exe`, ouvrir le dossier `splat_dataset` (ou le zip) comme jeu de données.
6. Laisser tourner. Avec 4 Go de mémoire vidéo, compter 10 à 30 minutes. Le plat apparaît et s'affine à l'écran ;
   on peut le faire tourner à la souris pendant le calcul.
7. M'envoyer 3 captures d'écran (dessus, côté, gros plan sur une zone brillante).

## Si ça bloque

- **Mémoire insuffisante / plantage** : relancer l'étape 3 avec des images plus petites :
  `.\preparer-essai-neuronal.ps1 --max-width 960`
- **Le plat est flou ou dédoublé** : m'envoyer la capture ; c'est le signe que les positions de l'iPhone doivent
  être affinées davantage avant l'entraînement.
- **Tout est noir sauf le plat** : normal, les images sont masquées en dehors de la boîte de scan.
  Pour garder le décor : `.\preparer-essai-neuronal.ps1 --no-masks`

## Ce que contient le jeu de données

`images/` (vues réduites à 1280 px), `masks/` (blanc = intérieur de la boîte), `transforms.json` (une caméra
par vue, repère de la boîte, mètres, +y vers le haut ; poses affinées par la finition quand elles existent),
`init_points.ply` (points mesurés du modèle final, pour démarrer l'entraînement au bon endroit).
