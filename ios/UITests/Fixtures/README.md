# Plats d'exemple du contrôle des écrans

Le dossier `Sessions/` contient trois plats, rangés exactement comme l'app les garde sur l'iPhone : un plat
terminé (image du résultat, modèle final, GLB et USDZ texturés, aperçu du milieu du scan), un plat en cours
de calcul et un scan interrompu.

Ils sont fabriqués par `tools/make_screen_fixture.py` : le vrai moteur reconstruit l'assiette de synthèse du
projet (`backend/tests/synthetic.py`). Aucune photographie et aucune donnée extérieure n'y entrent. Les
fichiers sont volontairement légers (maillage final et texture plus grossiers qu'un vrai résultat).

Pour les refaire, par exemple après un changement de format :

    cd backend && .venv/bin/python ../tools/make_screen_fixture.py
