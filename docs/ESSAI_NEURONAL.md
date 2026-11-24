# Essai de reconstruction neuronale (Google Colab, ou votre PC)

But : voir, sur un de VOS plats, ce que donne une reconstruction par « Gaussian splatting » à partir des
mêmes images que le scan actuel. C'est un essai manuel, pas encore intégré à l'app.

État honnête (23 novembre) :
- **Jamais exécuté sur une carte graphique** : aucun résultat visuel n'existe encore. Le premier sortira chez vous.
- **Essai à blanc sur processeur, refait le 23 novembre** : le programme d'entraînement a tourné 4 000 pas sur un
  scan de synthèse avec le vrai code de la bibliothèque gsplat 1.5.3 (densification, remise à zéro des opacités,
  écriture du modèle) et un rendu factice à la place de la carte graphique. Lecture des données, repère des
  caméras, boucle, évaluation, fichiers de sortie : tout est passé.
- **Relu par un contradicteur**, qui a comparé chaque appel au code de gsplat 1.5.3. Corrigé depuis :
  - cette version de gsplat ne remet jamais les opacités à zéro (une erreur dans son code, corrigée chez eux
    après cette version) : le programme le fait lui-même, sinon le modèle sortirait plus voilé ;
  - un calcul raté n'était pas signalé et les résultats du plat précédent pouvaient être montrés à la place ;
  - la note et l'image de comparaison portent maintenant sur le modèle livré, et l'image est remise à l'endroit
    (un téléphone tenu droit enregistre ses photos couchées) ;
  - l'outil de préparation prend le dernier scan **terminé**, plus le dossier le plus récent.
- **Le point le plus incertain** : à chaque nouvelle session, Colab doit construire la partie « carte graphique »
  de gsplat (Colab a aujourd'hui Python 3.13, PyTorch 2.14 et CUDA 13, plus récents que ceux pour lesquels cette
  version a été écrite). Rien ne s'y oppose à la lecture, mais cette construction n'a pas pu être essayée ici.
  Le carnet la fait dans une cellule à part, avec son message, avant le calcul.
- L'animation du plat qui tourne est une image animée (`turntable.webp`), écrite sans encodeur vidéo : l'ancien
  fichier MP4 passait par un encodeur sous GPL, contraire à la règle de licences du projet.
- `preparer-essai-neuronal.ps1` n'a jamais été exécuté sous Windows par le projet (pas de Windows ici) ; la
  partie Python qu'il lance a été exécutée sous Linux.

## A. Préparer le scan (sur le PC)

1. Mettre le calculateur à jour : `git pull`, relancer `start-calculator.ps1`.
2. Scanner un plat avec l'app, aller jusqu'à **Terminer** et attendre « Modèle prêt ».
3. Dans le dossier du projet : clic droit sur `preparer-essai-neuronal.ps1` → *Exécuter avec PowerShell*.
   Il prend le dernier scan terminé et affiche où se trouve le fichier à envoyer, à la ligne `Zip:`
   (`...\sessions\<id>\splat_dataset.zip`). La fenêtre reste ouverte jusqu'à ce que vous appuyiez sur Entrée.

## B. Calculer dans Google Colab (recommandé)

1. Ouvrir le carnet dans Colab : tant que le dépôt est public, ce lien suffit :
   <https://colab.research.google.com/github/Omazi/dishplay3d/blob/main/colab/essai_neuronal.ipynb>.
   Sinon : <https://colab.research.google.com> → *Fichier → Importer le notebook* → choisir `colab/essai_neuronal.ipynb`
   (dans le dossier du projet après `git pull`).
2. *Exécution → Modifier le type d'exécution → GPU T4*.
3. Lancer les cellules de haut en bas. À l'étape « Envoyer le scan », choisir `splat_dataset.zip`.
4. À chaque nouvelle session Colab, l'étape 2 du carnet construit la bibliothèque pour la carte graphique :
   plusieurs minutes (durée jamais mesurée), avec beaucoup de lignes de compilation.
5. À la fin : une image « vraie photo | modèle », une animation du plat qui tourne, et un zip à télécharger.
   Pour regarder le modèle en 3D : <https://superspl.at/editor>, y glisser `splat.compressed.ply` (le plat peut y
   apparaître à l'envers : c'est la convention de ce visualiseur).
6. M'envoyer l'image de comparaison et une capture de l'animation (ou le zip).

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
