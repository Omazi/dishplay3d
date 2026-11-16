# Premier essai réel, de A à Z

Durée : ~30 min la première fois. Matériel : PC Windows/Linux, iPhone (iPhone 13 sans LiDAR = chemin standard),
même Wi‑Fi, un vrai plat posé sur une table, un mètre ruban.

1. **Calculateur** : `start-calculator.ps1` (Windows) ou `./start-calculator.sh` (Linux). Noter l'adresse, le code
   à 6 chiffres et l'empreinte. Le diagnostic doit afficher `[OK]` partout (sinon voir `SETUP_WINDOWS_LINUX.md`).
2. **App** : installer DishPlay Scan depuis TestFlight (`TESTFLIGHT.md`). Ouvrir le QR (page `https://127.0.0.1:8765/`
   sur le PC, ou le QR du terminal) avec l'**appareil photo** de l'iPhone → « Ouvrir dans DishPlay Scan ».
   Autoriser **Réseau local**, puis la caméra. L'écran « Connexion » doit indiquer « Calculateur joignable » et
   « Pas de LiDAR : reconstruction par stéréo des images ». Laisser le LiDAR désactivé pour ce premier essai.
3. **Plat** : immobile, lumière diffuse (pas de soleil direct ni spot), table texturée de préférence. Mesurer la
   largeur du contenant et la saisir dans « Mesure de contrôle ». Prendre 3–4 photos de contrôle à part.
   Éviter pour ce premier essai les objets transparents ou miroirs.
4. **Boîte** : « Ouvrir le scanner », toucher la table à côté du plat. Ajuster : poignées orange (largeur), bleues
   (profondeur), jaune (hauteur), disque central (déplacer), deux doigts (tourner), ou les curseurs (cm).
   La boîte doit inclure le bord du contenant et les aliments, sans englober toute la table.
5. **Démarrer** : la boîte devient verte et se verrouille. Tourner lentement autour du plat à ~30–40 cm, vue
   oblique (~35°), puis un second passage plus haut pour voir l'intérieur. Suivre les messages (« ralentis »,
   « complète ce côté », « monte légèrement »…). Ne jamais toucher le plat. Les vues sont choisies automatiquement.
6. **Panneau du bas** : après quelques vues (objectif < 15 s), des points colorés apparaissent (« Nuage reconstruit
   (provisoire) »), puis « Nuage + surface partielle ». La ligne d'état indique la version, la dernière vue
   intégrée, l'âge du résultat, les points, triangles et la surface mesurée. Glisser pour tourner, pincer pour
   zoomer, bouton ↗ pour agrandir — la capture continue. **Pause** : vérifier en tournant la vue que c'est une
   géométrie 3D (relief, creux), pas une photo plaquée.
7. **Zone insuffisante** : reprendre et compléter un côté ; vérifier que la version, la dernière vue intégrée et la
   surface mesurée changent. « Angles » (téléphone) et « surface mesurée » (calculateur) sont deux indicateurs
   distincts.
8. **Terminer** : l'app envoie les dernières vues puis lance la finition (re-stéréo plus fine, maillage maître,
   texture). Le modèle final s'affiche dans le panneau. Comparer aux photos de contrôle ; vérifier que l'assiette
   reste creuse.
9. **Exporter** (bouton) : zip de la session côté iPhone (originaux, métadonnées, résultats). Côté PC :
   `~/dishplay-scan-data/sessions/<id>/final/` (model.glb, mesh.ply, points.ply, texture.png, report.json).
   Rejouer à l'identique sans refaire le tour :
   ```bash
   backend/.venv/bin/python tools/verify_capture.py ~/dishplay-scan-data/sessions/<id>
   backend/.venv/bin/python tools/replay_session.py local ~/dishplay-scan-data/sessions/<id> --out replay_out --finish
   backend/.venv/bin/python tools/render_geometry.py replay_out/final/final_preview.dpg rendu.png --mode mesh
   ```
10. **À renvoyer pour le rapport** : enregistrement d'écran continu (Centre de contrôle › Enregistrement de l'écran)
    montrant points puis surface AVANT Terminer, `report.json`, le zip de session, le log du terminal du PC.

Essais d'échec à faire ensuite : couper le Wi‑Fi 20 s pendant le scan (le panneau indique « calculateur
déconnecté », les vues s'accumulent sur l'iPhone puis partent au retour), refuser Réseau local, mettre la caméra
contre la table (suivi limité), pièce sombre, assiette blanche unie, déplacer le plat (doit dégrader, pas être caché).
