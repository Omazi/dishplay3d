# Essai de reconstruction neuronale (Google Colab, ou votre PC)

But : voir, sur un de VOS plats, ce que donne une reconstruction par « Gaussian splatting » à partir des
mêmes images que le scan actuel. C'est un essai manuel, pas encore intégré à l'app.

État honnête :
- **Testé** : la préparation du jeu de données (test automatique + vérification sur une vraie capture iPhone) ;
  le programme d'entraînement `backend/reconstruction/splat_train.py` en essai à blanc sur processeur (lecture des données, repère
  des caméras, boucle, évaluation, export du modèle, vidéo), avec un rendu factice à la place de la carte graphique.
- **Jamais exécuté** : le vrai rendu sur carte graphique, donc aucun résultat visuel n'existe encore.
  Le premier sortira chez vous.

## A. Préparer le scan (sur le PC)

1. Mettre le calculateur à jour : `git pull`, relancer `start-calculator.ps1`.
2. Scanner un plat avec l'app, aller jusqu'à **Terminer** et attendre « Modèle prêt ».
3. Dans le dossier du projet : clic droit sur `preparer-essai-neuronal.ps1` → *Exécuter avec PowerShell*.
   Il affiche le dossier créé (`...\sessions\<id>\splat_dataset`) et le fichier `splat_dataset.zip` juste à côté.

## B. Calculer dans Google Colab (recommandé)

1. Ouvrir <https://colab.research.google.com> → *Fichier → Importer le notebook* → choisir `colab/essai_neuronal.ipynb`
   (dans le dossier du projet après `git pull`).
2. *Exécution → Modifier le type d'exécution → GPU T4*.
3. Lancer les cellules de haut en bas. À l'étape « Envoyer le scan », choisir `splat_dataset.zip`.
4. La première exécution compile la bibliothèque pour la carte graphique : plusieurs minutes sans affichage.
5. À la fin : une image « vraie photo | modèle », une vidéo du plat qui tourne, et un zip à télécharger.
6. M'envoyer l'image de comparaison et une capture de la vidéo (ou le zip).

Si une cellule affiche une erreur en rouge : m'envoyer une capture du message, sans rien corriger.

## C. Variante sans Colab : Brush sur le PC (GTX 1650)

Télécharger Brush (libre, un seul programme) : <https://github.com/ArthurBrussee/brush/releases>, lancer
`brush_app.exe`, ouvrir le dossier `splat_dataset`. Avec 4 Go de mémoire vidéo, compter 10 à 30 minutes.
En cas de manque de mémoire : `.\preparer-essai-neuronal.ps1 --max-width 960`.

## Ce que contient le jeu de données

`images/` (vues réduites à 1280 px), `masks/` (blanc = intérieur de la boîte), `transforms.json` (une caméra
par vue, repère de la boîte, mètres, +y vers le haut ; poses affinées par la finition quand elles existent),
`init_points.ply` (points mesurés du modèle final, pour démarrer l'entraînement au bon endroit).

## Ce que mesure le carnet

Une vue sur huit n'est jamais utilisée pour l'entraînement. Le modèle est ensuite rendu depuis ces positions et
comparé à la vraie photo (`heldout_psnr_db` dans `report.json`, plus c'est haut mieux c'est). C'est la première
mesure de ressemblance sur de vraies images dans ce projet.
