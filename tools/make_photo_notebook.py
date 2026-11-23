#!/usr/bin/env python3
"""Build colab/photo_express.ipynb. The notebook is self-contained: it embeds tools/photo_express.py, so it works
without access to this repository.   python tools/make_photo_notebook.py [--check]"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "colab" / "photo_express.ipynb"
sys.path.insert(0, str(ROOT / "tools"))

# Chosen to fit what Colab has installed on 23 Nov 2026 (Python 3.13, torch 2.14, transformers 5.23, numpy 2.4,
# Pillow 11.3, scikit-image 0.25, omegaconf 2.4.0, einops 0.8.2) without upgrading any of it: rembg 2.0.69 is the
# last version that does not ask for a newer numpy, Pillow and scikit-image. TripoSR's own requirements.txt is
# deliberately not installed: see the header of tools/photo_express.py.
PACKAGES = "trimesh==5.2.2 rembg==2.0.69 onnxruntime omegaconf==2.4.0 einops==0.8.2 scikit-image imageio"


def md(s):
    return {"cell_type": "markdown", "metadata": {}, "source": s.strip("\n").splitlines(keepends=True)}


def code(s):
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": s.strip("\n").splitlines(keepends=True)}


def build() -> dict:
    from photo_express import TRIPOSR_COMMIT
    program = (ROOT / "tools" / "photo_express.py").read_text()
    cells = [
        md("""
# DishPlay — photo express : une photo → un modèle 3D (essai)

Ce carnet prend **une seule photo** d'un plat et fabrique un modèle 3D complet par IA générative (modèle TripoSR, licence MIT).

**À savoir avant de juger le résultat**
- Les côtés que la photo ne montre pas sont **inventés** : le dessus ressemblera à la photo, le dos et le dessous sont une supposition.
- Rien n'est mesuré : la taille du modèle est arbitraire.
- Ce carnet n'a jamais tourné en entier avant vous. Si une cellule affiche une erreur en rouge, envoyez une capture du message, sans rien corriger.

**La photo** : le plat entier dans l'image, vu de trois quarts (ni de face, ni tout à fait du dessus), bien éclairé, sur un fond simple. Format JPEG ou PNG.

**Avant de commencer** : menu *Exécution → Modifier le type d'exécution → GPU T4*, puis lancez les cellules une par une, de haut en bas (bouton ▶ à gauche de chaque cellule).
"""),
        md("## 1. Vérifier la carte graphique"),
        code("""
import shutil, subprocess
gpu = ""
if shutil.which("nvidia-smi"):
    gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"], capture_output=True, text=True).stdout.strip()
print(gpu or "Pas de carte graphique : le calcul marchera quand même, en plusieurs minutes au lieu de quelques secondes. "
      "Pour en avoir une : menu Exécution > Modifier le type d'exécution > GPU T4.")
"""),
        md("""
## 2. Installer les outils (1 à 2 minutes)

Le code du modèle est pris à une version précise, et seuls les outils nécessaires sont installés. Si des lignes de
`pip` parlent de conflits entre d'autres paquets, ignorez-les : elles ne concernent pas ce carnet, et il n'y a pas
besoin de redémarrer la session.
"""),
        code(f"""
!rm -rf /content/TripoSR && git clone -q https://github.com/VAST-AI-Research/TripoSR.git /content/TripoSR
!cd /content/TripoSR && git checkout -q {TRIPOSR_COMMIT} && git log --oneline -1
!pip -q install {PACKAGES}
!python -c "import torch, transformers, numpy, skimage, trimesh, rembg; print('torch', torch.__version__, '| transformers', transformers.__version__, '| numpy', numpy.__version__, '| scikit-image', skimage.__version__, '| trimesh', trimesh.__version__)"
"""),
        md("## 3. Le programme de calcul\n\nRien à modifier : cette cellule écrit le programme sur la machine Colab, puis la suivante le vérifie."),
        code("%%writefile /content/photo_express.py\n" + program),
        code("""
!python /content/photo_express.py --self-test
assert _exit_code == 0, "La vérification du programme a échoué : envoyez une capture de cette cellule."
"""),
        md("## 4. Envoyer la photo du plat"),
        code("""
import os
from google.colab import files
up = files.upload()
if not up:
    raise SystemExit("Aucune photo reçue : relancez cette cellule et choisissez une photo.")
name = next(iter(up))
PHOTO = "/content/photo_du_plat" + (os.path.splitext(name)[1].lower() or ".jpg")
with open(PHOTO, "wb") as f:
    f.write(up[name])
print("Reçu :", name)
"""),
        md("""
## 5. Fabriquer le modèle

À chaque nouvelle session Colab, le modèle (1,7 Go) et l'outil de détourage se téléchargent d'abord : une à deux minutes. Le calcul lui-même prend quelques secondes avec la carte graphique.
"""),
        code("""
!rm -rf /content/resultat
!python /content/photo_express.py "$PHOTO" --triposr /content/TripoSR --out /content/resultat
assert _exit_code == 0, "Le calcul a échoué : envoyez une capture de CETTE cellule (le message est juste au-dessus)."
"""),
        md("""
## 6. Voir le résultat

D'abord une image : à gauche le plat détouré (ce que le modèle a vu), puis le modèle vu de cinq endroits. « photo » est le côté photographié et doit ressembler à l'image de gauche ; « dos » est le côté opposé, entièrement inventé ; « dessus » est la vue de haut. Ensuite le modèle en 3D : faites-le tourner avec le doigt ou la souris.
"""),
        code("""
import base64, json, os
from IPython.display import Image, HTML, display
R = "/content/resultat"
rep = json.load(open(f"{R}/report.json"))
print(f"{rep['triangles']} triangles, {rep['seconds']['total']} s au total ({rep['device']})")
display(Image(f"{R}/apercu.jpg"))
glb = f"{R}/plat_apercu.glb" if os.path.exists(f"{R}/plat_apercu.glb") else f"{R}/plat.glb"
b = base64.b64encode(open(glb, "rb").read()).decode()
display(HTML(f'''<script type="module" src="https://ajax.googleapis.com/ajax/libs/model-viewer/4.0.0/model-viewer.min.js"></script>
<model-viewer src="data:model/gltf-binary;base64,{b}" alt="Le plat en 3D" camera-controls auto-rotate shadow-intensity="0.6"
  style="width:100%;max-width:760px;height:520px;background:#151613"></model-viewer>'''))
"""),
        md("""
## 7. Télécharger

`plat.glb` est le modèle complet. À m'envoyer pour juger ensemble : `apercu.jpg` et, si possible, la photo d'origine.
"""),
        code("""
!cd /content/resultat && zip -q -r /content/photo_express_resultat.zip .
files.download("/content/photo_express_resultat.zip")
"""),
    ]
    return {"cells": cells, "nbformat": 4, "nbformat_minor": 0,
            "metadata": {"accelerator": "GPU", "colab": {"gpuType": "T4", "provenance": []},
                         "kernelspec": {"display_name": "Python 3", "name": "python3"}, "language_info": {"name": "python"}}}


def main():
    text = json.dumps(build(), ensure_ascii=False, indent=1) + "\n"
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text() != text:
            sys.exit("colab/photo_express.ipynb is out of date: run python tools/make_photo_notebook.py")
        print("notebook up to date")
        return
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(text)
    print(f"written {OUT}")


if __name__ == "__main__":
    main()
