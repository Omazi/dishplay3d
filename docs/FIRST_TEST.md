# Premier essai réel, de A à Z

Durée : environ 30 minutes la première fois. Il faut : le PC (Windows ou Linux), l'iPhone, les deux sur le
**même Wi‑Fi**, un plat posé sur une table et, si vous voulez vérifier la taille du modèle, un mètre ruban.

Les mots entre guillemets sont ceux de l'app 1.7.1 et du calculateur `p1-0.11.0`.

> État honnête : cette marche à suivre décrit l'app telle qu'elle est écrite et telle qu'elle s'affiche dans le
> simulateur de GitHub (`docs/SCREEN_CHECK.md`). Je n'ai pas d'iPhone : la caméra, le suivi du mouvement, le
> réseau réel et la réalité augmentée ne sont vérifiés que par votre essai.

## 1. Le calculateur, sur le PC

- Windows : double-cliquer sur `Demarrer-le-calculateur.cmd`. Linux : `./start-calculator.sh`.
- La première fois, l'installation prend plusieurs minutes et Windows demande **une fois** votre accord pour
  ouvrir le pare-feu. Le Wi‑Fi du PC doit être déclaré « privé » dans Windows.
- À la fin, la fenêtre affiche un **QR code** et un code à 6 chiffres. Laissez cette fenêtre ouverte : la fermer
  arrête le calculateur.

Détails et dépannage : `SETUP_WINDOWS_LINUX.md`.

## 2. Relier l'iPhone

1. Installer DishPlay Scan avec TestFlight (`TESTFLIGHT.md`) et l'ouvrir une fois.
2. Avec l'**appareil photo** de l'iPhone, viser le QR code du calculateur, puis toucher « Ouvrir dans DishPlay Scan ».
3. Accepter « Réseau local » quand l'iPhone le demande.
4. L'accueil doit afficher « Calculateur relié ». Dans Réglages, sous ce titre : « Il répond en … ms · moteur
   p1-0.11.0 ». Un moteur plus ancien s'accompagne d'un message qui demande de mettre le calculateur à jour.

Si l'accueil affiche « Calculateur injoignable » : toucher cette pastille, Réglages dit quoi vérifier.

## 3. Facultatif : la largeur réelle

Mesurez la largeur de l'assiette et saisissez-la dans Réglages › « Largeur réelle du contenant ». Elle ne sert
qu'au scan suivant et ne change rien au modèle : la fiche du plat affichera « Largeur mesurée : … cm pour … cm
saisis », ce qui dit si le modèle a la bonne taille.

## 4. Le plat

Immobile, sous une lumière douce (ni soleil direct ni spot), sur une table qui n'est pas unie si possible.
Pour ce premier essai, évitez le verre et les surfaces miroir.

## 5. La boîte

1. Accueil › « Scanner un plat ». Autoriser la caméra.
2. « Placez la boîte » : toucher la table au pied du plat.
3. « Centrez la boîte sur le plat » : glisser pour la déplacer, pincer pour changer sa taille, tirer une poignée
   pour régler un côté. La ligne des dimensions ouvre des curseurs (largeur, profondeur, hauteur, rotation).
4. La boîte doit contenir tout le plat, **hauteur comprise**, sans englober la table.

## 6. Le scan

1. « Démarrer le scan ». Tournez lentement autour du plat, à 30–40 cm, l'iPhone incliné vers lui ; puis refaites
   un passage plus haut, pour voir l'intérieur.
2. L'anneau se remplit à mesure que les côtés sont vus (« Côtés vus 12/12 · dessus 6/6 » quand tout y est), et
   l'app dit de quel côté aller. En bas, « Aperçu en direct » montre le plat qui se construit, en points puis en
   surface.
3. Suivez les consignes (« Ralentissez », « Montez un peu », « Recadrez »…). Ne touchez pas le plat.
4. Pause : le bouton à gauche. Le scan est conservé ; « Boîte » permet de corriger la boîte.

## 7. Terminer

1. Quand l'app affiche « Scan réussi : vous pouvez terminer », toucher « Terminer le scan ». Si elle affiche
   « Scan correct » ou « Scan insuffisant », elle dit ce qui manque ; vous pouvez continuer le tour ou terminer
   quand même.
2. Le calcul dure quelques minutes : « Étape 1 sur 4 : mesure des reliefs », puis l'alignement des vues, la
   surface et les couleurs, avec le temps restant quand il peut être estimé.
3. Vous pouvez quitter cet écran : le calcul continue sur le PC et le plat arrive dans « Mes plats ».
4. « Modèle prêt » : l'app indique la qualité du modèle et, s'il y a lieu, ce que le calcul n'a pas pu faire.

## 8. Le résultat

« Voir dans Mes plats », puis toucher le plat :

- « Qualité du modèle » (bonne, correcte, insuffisante), et « Largeur mesurée » si une largeur avait été saisie ;
- « Voir sur votre table » : le modèle avec ses couleurs, en 3D ou posé sur la table en réalité augmentée ;
- « Partager le modèle 3D » : un fichier `.glb` au nom du plat ;
- « Exporter le dossier complet » : tout ce que l'iPhone garde de ce plat, vues comprises, en un fichier zip.

## 9. Plusieurs plats à la suite

Vous pouvez scanner le plat suivant pendant que le calculateur termine le précédent. Pendant ce temps l'aperçu
en direct ne s'affiche pas (l'app le dit, vos vues sont gardées), et le modèle demandé attend son tour : « En
attente, 1er dans la file ». Rien n'est à relancer.

## 10. Essais d'échec utiles

- Couper le Wi‑Fi 20 secondes pendant le scan : « Calculateur injoignable », les vues restent sur l'iPhone et
  partent au retour du réseau.
- Fermer la fenêtre du calculateur pendant un calcul, puis le relancer : le calcul reprend tout seul.
- Quitter un scan en pause en choisissant « Garder le scan pour plus tard » : il se termine depuis l'accueil
  (« Scan interrompu » › « Envoyer et terminer »).
- Pièce sombre, assiette blanche unie, caméra trop près de la table : l'app doit le dire, pas le cacher.

## Si quelque chose ne va pas, à m'envoyer

- une capture d'écran de l'iPhone au moment du problème ;
- le fichier `calculateur.log` du dossier des données du PC (`dishplay-scan-data`, dans votre dossier personnel) ;
- si le modèle déçoit : « Exporter le dossier complet » depuis la fiche du plat (le fichier contient vos photos).

Pour rejouer un scan sur le PC sans refaire le tour : `tools/replay_session.py` (voir l'en-tête du fichier).
