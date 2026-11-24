# Contrôle des écrans de l'app iPhone

But : voir l'app telle qu'elle s'affiche vraiment avant de la publier, sans iPhone sous la main.

Des tests (`ios/UITests`) ouvrent chaque écran dans le simulateur iPhone des machines de GitHub, en gardent
une image et y passent l'audit d'accessibilité d'Apple. Rien n'est jugé automatiquement : les images se
regardent. Trois parcours : clair, sombre, très grand texte (235 %).

Le même travail lance, sur l'iPhone de référence, les tests de la logique de l'app : ceux de `ScanCore`
(formats échangés avec le calculateur, file d'attente, mots affichés) et ceux de `ios/AppTests`, qui tournent
dans l'app elle-même (ce qui est gardé sur l'iPhone, repris après une coupure, vraiment effacé quand un scan est
abandonné). Un seul de ces tests en échec fait échouer le travail, donc bloque une publication.

## Le lancer

Modifier `ios/UITests/RUN.txt` (sur `main` ou sur une branche `claude/…`) et pousser. Le travail GitHub
« DishPlay Scan — screens » démarre ; il dure 20 à 25 minutes pour les trois parcours. Deux lignes facultatives
dans ce fichier :

- `only: light` (ou `dark`, `largeText`) : un seul parcours, pour regarder un changement plus vite ;
- `devices: all` : en plus de l'iPhone de référence (iPhone récent, dernier iOS), un iPhone de 6,1 pouces sous
  iOS 18 (l'app sans le verre d'iOS 26), le plus petit écran pris en charge et un iPad (l'app est déclarée pour
  iPad : ses écrans s'y regardent aussi).

Ce travail coûte des minutes de Mac : il ne tourne que sur demande.

## Avant une version

La publication (`docs/TESTFLIGHT.md`) refuse de partir sans un passage **complet et réussi** de ce contrôle sur
le même code de l'app : les trois parcours, donc un `RUN.txt` sans ligne `only:`. L'ordre est donc :

1. mettre le numéro de version dans `ios/project.yml` ;
2. pousser sur la branche de travail avec `RUN.txt` modifié, sans `only:` ;
3. regarder les images ;
4. seulement ensuite, pousser sur `main` les notes de version (`ios/RELEASE_NOTES.txt`), sans retoucher l'app.

## Lire le résultat

- Les images en taille réelle et le journal complet sont dans les fichiers joints du travail
  (`scan-screens-…`), à télécharger depuis la page du travail sur GitHub.
- Des copies réduites, avec les constats de l'audit (`audit.txt`), sont aussi écrites en texte dans le journal
  de l'étape « Pictures and audit findings », entre deux lignes de repère. C'est ce que lit une session de
  travail qui ne peut pas télécharger les fichiers joints.
- La première étape fait ouvrir le fichier USDZ d'exemple par les lecteurs d'Apple (Model I/O, RealityKit,
  SceneKit) : nombre de maillages, taille en centimètres, texture trouvée ou non, et une image.

## Ce que ce contrôle ne voit pas

Le simulateur n'a ni caméra ni calculateur. L'app est donc lancée avec des options réservées aux versions de
développement (`ios/App/UITestMode.swift`, absentes de la version publiée) : plats d'exemple, calculateur
relié mais muet, écran de scan placé à huit moments d'un scan (dont : scanner pendant que le calculateur
termine un autre plat, modèle qui attend son tour, modèle jugé « correct »). Le suivi AR, la pose de la boîte, la prise de
vues, le réseau réel et la réalité augmentée (« Voir sur votre table ») ne se vérifient que sur un iPhone.

Les plats d'exemple viennent de l'assiette de synthèse du projet, reconstruite par le vrai moteur
(`tools/make_screen_fixture.py`).
