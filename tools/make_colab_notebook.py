#!/usr/bin/env python3
"""Build colab/essai_neuronal.ipynb. The notebook is self-contained: it embeds backend/reconstruction/splat_train.py, so it
works without access to this (private) repository.   python tools/make_colab_notebook.py [--check]"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "colab" / "essai_neuronal.ipynb"


def md(s):
    return {"cell_type": "markdown", "metadata": {}, "source": s.strip("\n").splitlines(keepends=True)}


def code(s):
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": s.strip("\n").splitlines(keepends=True)}


def build() -> dict:
    trainer = (ROOT / "backend" / "reconstruction" / "splat_train.py").read_text()
    cells = [
        md("""
# DishPlay Scan — essai de reconstruction neuronale

Ce carnet prend le fichier `splat_dataset.zip` d'un scan et calcule un modèle 3D par « Gaussian splatting ».

**Avant de commencer** : menu *Exécution → Modifier le type d'exécution → GPU T4*, puis lancer les cellules une par une, de haut en bas (bouton ▶ à gauche de chaque cellule).
"""),
        md("## 1. Vérifier la carte graphique"),
        code("""
import torch
assert torch.cuda.is_available(), "Pas de carte graphique : menu Exécution > Modifier le type d'exécution > GPU T4, puis relancez cette cellule."
print("Carte graphique :", torch.cuda.get_device_name(0), "-", round(torch.cuda.get_device_properties(0).total_memory / 2**30), "Go")
"""),
        md("""
## 2. Installer les outils et les préparer pour la carte graphique

À chaque nouvelle session Colab, la bibliothèque de calcul se construit pour la carte graphique : comptez plusieurs minutes (durée jamais mesurée), avec beaucoup de lignes de compilation. C'est l'étape la plus incertaine du carnet : elle n'a jamais pu être essayée. Si elle échoue, envoyez une capture de la fin du message, sans rien corriger.
"""),
        code("""
!pip -q install gsplat==1.5.3
%env MAX_JOBS=2
!nvcc --version | tail -1
!VERBOSE=1 python -c "from gsplat.cuda._backend import _C; assert _C is not None, 'construction impossible'; print('gsplat pret pour la carte graphique')"
assert _exit_code == 0, "La bibliothèque ne s'est pas construite : envoyez une capture de la fin du message ci-dessus."
"""),
        md("## 3. Le programme de calcul\n\nRien à modifier : cette cellule écrit le programme sur la machine Colab."),
        code("%%writefile /content/splat_train.py\n" + trainer),
        md("""
## 4. Envoyer le scan

Sur le PC, `preparer-essai-neuronal.ps1` a créé un fichier `splat_dataset.zip` dans le dossier de la session. Choisissez-le ici.
"""),
        code("""
from google.colab import files
up = files.upload()
if not up:
    raise SystemExit("Aucun fichier reçu : relancez cette cellule et choisissez splat_dataset.zip.")
name = next(iter(up))
ZIP = "/content/scan_a_calculer.zip"
with open(ZIP, "wb") as f:
    f.write(up[name])
print("Reçu :", name)
"""),
        md("""
## 5. Calculer le modèle

Une ligne s'affiche tous les 250 pas. Si la session Colab a été redémarrée, relancez d'abord les cellules 2 à 4.
"""),
        code("""
STEPS = 7000   # 15000 pour un résultat plus fin (plus long)
!rm -rf /content/resultat
!python /content/splat_train.py --data "$ZIP" --out /content/resultat --steps $STEPS
assert _exit_code == 0, "Le calcul a échoué : envoyez une capture de CETTE cellule (le message est juste au-dessus)."
"""),
        md("## 6. Voir le résultat\n\nÀ gauche la vraie photo (jamais utilisée pour l'entraînement), à droite le modèle vu du même endroit. Puis quatre vues du modèle, et le modèle qui tourne."),
        code("""
import json, base64
from IPython.display import Image, HTML, display
rep = json.load(open("/content/resultat/report.json"))
print({k: v for k, v in rep.items() if k != "log"})
display(Image("/content/resultat/compare.jpg"))
display(Image("/content/resultat/preview.jpg"))
try:
    b = base64.b64encode(open("/content/resultat/turntable.webp", "rb").read()).decode()
    display(HTML(f'<img width="640" alt="Le modèle qui tourne" src="data:image/webp;base64,{b}">'))
except FileNotFoundError:
    print("Pas d'animation (voir le message plus haut)")
"""),
        md("""
## 7. Télécharger

Le zip contient les images, l'animation, le rapport et `splat.compressed.ply`, le modèle allégé. Pour le regarder en 3D : https://superspl.at/editor, glisser ce fichier dans la page. Le plat peut y apparaître à l'envers : c'est la convention de ce visualiseur, pas un défaut du modèle. Le modèle non allégé (`splat.ply`, plus lourd) reste sur la machine Colab, dans `/content/resultat`.
"""),
        code("""
!cd /content/resultat && zip -q -r /content/resultat_dishplay.zip . -x "dataset/*" "splat.ply"
files.download("/content/resultat_dishplay.zip")
"""),
    ]
    return {"cells": cells, "nbformat": 4, "nbformat_minor": 0,
            "metadata": {"accelerator": "GPU", "colab": {"gpuType": "T4", "provenance": []},
                         "kernelspec": {"display_name": "Python 3", "name": "python3"}, "language_info": {"name": "python"}}}


def main():
    text = json.dumps(build(), ensure_ascii=False, indent=1) + "\n"
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text() != text:
            sys.exit("colab/essai_neuronal.ipynb is out of date: run python tools/make_colab_notebook.py")
        print("notebook up to date")
        return
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(text)
    print(f"written {OUT}")


if __name__ == "__main__":
    main()
