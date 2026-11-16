#!/usr/bin/env python3
"""Build colab/essai_neuronal.ipynb. The notebook is self-contained: it embeds tools/splat_train.py, so it
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
    trainer = (ROOT / "tools" / "splat_train.py").read_text()
    cells = [
        md("""
# DishPlay Scan — essai de reconstruction neuronale

Ce carnet prend le fichier `splat_dataset.zip` d'un scan et calcule un modèle 3D par « Gaussian splatting ».

**Avant de commencer** : menu *Exécution → Modifier le type d'exécution → GPU T4*, puis lancer les cellules une par une, de haut en bas (bouton ▶ à gauche de chaque cellule).
"""),
        md("## 1. Vérifier la carte graphique"),
        code("""
import torch, subprocess
print(subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"], capture_output=True, text=True).stdout)
assert torch.cuda.is_available(), "Pas de carte graphique : menu Exécution > Modifier le type d'exécution > GPU T4"
print("Carte graphique visible par PyTorch :", torch.cuda.get_device_name(0))
"""),
        md("## 2. Installer les outils (1 à 3 minutes)"),
        code("""
!pip -q install gsplat imageio imageio-ffmpeg
!python -c "import gsplat; print('gsplat', gsplat.__version__)"
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
ZIP = "/content/" + next(iter(up))
print("Reçu :", ZIP)
"""),
        md("""
## 5. Calculer le modèle

La toute première fois, la bibliothèque se compile pour la carte graphique : plusieurs minutes sans rien d'affiché, c'est normal. Ensuite une ligne s'affiche tous les 250 pas.
"""),
        code("""
STEPS = 7000   # 15000 pour un résultat plus fin (plus long)
!python /content/splat_train.py --data "$ZIP" --out /content/resultat --steps $STEPS
"""),
        md("## 6. Voir le résultat\n\nÀ gauche la vraie photo (jamais utilisée pour l'entraînement), à droite le modèle vu du même endroit."),
        code("""
import json, base64
from IPython.display import Image, HTML, display
rep = json.load(open("/content/resultat/report.json"))
print({k: v for k, v in rep.items() if k != "log"})
display(Image("/content/resultat/compare.jpg"))
display(Image("/content/resultat/preview.jpg"))
try:
    b = base64.b64encode(open("/content/resultat/turntable.mp4", "rb").read()).decode()
    display(HTML(f'<video width="640" controls loop autoplay muted src="data:video/mp4;base64,{b}"></video>'))
except FileNotFoundError:
    print("Pas de vidéo (voir le message plus haut)")
"""),
        md("## 7. Télécharger\n\n`splat.ply` s'ouvre dans un visualiseur de splats (par exemple https://superspl.at/editor : glisser le fichier dans la page)."),
        code("""
!cd /content/resultat && zip -q -r /content/resultat_dishplay.zip . -x "dataset/*"
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
