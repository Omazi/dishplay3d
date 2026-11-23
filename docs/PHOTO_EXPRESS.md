# Photo express : une photo → un modèle 3D (essai sur Google Colab)

But : voir, sur un de VOS plats, ce que donne l'IA générative à partir d'**une seule photo**. C'est un essai à
part : il n'utilise ni l'app, ni le calculateur, ni votre PC. Il ne remplace pas le scan.

## Ce qu'il faut savoir avant de juger

- Les côtés que la photo ne montre pas sont **inventés** par le modèle. Le dessus ressemblera à la photo ; le dos
  et le dessous sont une supposition plausible. Le scan mesure, cet essai devine.
- Rien n'est mesuré : la taille du modèle est arbitraire.
- Le modèle utilisé (TripoSR, 2024) est le seul que j'ai trouvé dont le code, les poids et les composants
  obligatoires sont tous sous licence permissive. Les modèles plus récents font mieux, mais chacun dépend d'au
  moins un composant sous licence à conditions (voir plus bas).

## Marche à suivre (10 minutes)

1. Prendre la photo : le plat entier dans l'image, vu de trois quarts (ni de face, ni tout à fait du dessus),
   bien éclairé, sur un fond simple. Format JPEG ou PNG.
2. Ouvrir le carnet dans Colab : tant que le dépôt est public, ce lien suffit :
   <https://colab.research.google.com/github/Omazi/dishplay3d/blob/main/colab/photo_express.ipynb>
   (depuis un ordinateur de préférence ; depuis le téléphone, non essayé).
   Sinon : <https://colab.research.google.com> → *Fichier → Importer le notebook* → choisir le fichier
   `colab/photo_express.ipynb` du projet.
3. *Exécution → Modifier le type d'exécution → GPU T4*.
4. Lancer les cellules de haut en bas. À l'étape « Envoyer la photo », choisir la photo.
5. À la fin : une image de contrôle (le plat détouré, puis le modèle vu de cinq endroits : « photo », deux
   profils, « dos », « dessus »), le modèle en 3D que l'on fait tourner au doigt, et un zip à télécharger
   (`plat.glb`, `plat_apercu.glb`, `apercu.jpg`, `decoupe.png`, `report.json`).
6. M'envoyer `apercu.jpg` et la photo d'origine. La vue « photo » doit ressembler à la photo : si elle montre
   un autre côté, dites-le-moi (c'est le seul point d'orientation que je n'ai pas pu contrôler sans le modèle).

Si une cellule affiche une erreur en rouge : m'envoyer une capture du message, sans rien corriger.

## État honnête

- **Jamais exécuté en entier.** Sur la machine de développement, l'exécution du modèle téléchargé a été refusée
  par la protection de la session. La première vraie exécution sera la vôtre.
- **Tests automatiques, relancés à chaque contrôle du projet** (`backend/tests/test_photo_notebook.py`) : le
  fichier GLB (couleurs, matière, normales, relu octet par octet), l'image de contrôle et son orientation, la
  lecture d'une photo d'iPhone (rotation, taille), le renommage des paramètres du modèle, l'arrêt du carnet en
  cas d'échec, et le fait que le carnet ne demande rien hors de votre règle.
- **Vérifié à la main le 23 novembre, dans un environnement séparé** (PyTorch 2.15, transformers 5.24,
  scikit-image 0.26, trimesh 5.2) : l'extraction de la surface qui remplace `torchmcubes` (axes et sens des
  faces, sur une forme de synthèse ; le carnet relance ce contrôle sur Colab), le renommage comparé aux vrais
  noms de la bibliothèque installée, et l'affichage du fichier GLB par le visualiseur du carnet dans un
  navigateur (bon côté devant, couleurs justes).
- **Vérifié à la lecture seulement** : les appels au code de TripoSR (version figée). Un relecteur indépendant
  a relu ces appels et trouvé une erreur bloquante, corrigée depuis : les versions récentes de `transformers`
  (5.9 et suivantes, donc celle de Colab) ont renommé les paramètres de l'encodeur d'image, et le fichier du
  modèle ne se chargeait plus. Le programme les renomme ; que le résultat soit numériquement identique à celui
  de l'ancienne version n'a pas pu être vérifié sans exécuter le modèle.
- Différence connue : les versions récentes de `transformers` agrandissent la grille de positions de l'encodeur
  par une formule légèrement différente de celle de 2023. Effet attendu négligeable, non mesuré.
- Tout n'est pas figé : le code et les poids de TripoSR le sont ; PyTorch, transformers et scikit-image sont
  ceux de Colab le jour de l'essai (le carnet les affiche), et la configuration de l'encodeur est prise sur sa
  branche principale.
- Le modèle garde ses couleurs par sommet, sans image de texture : suffisant pour juger dans un navigateur.
  Le carnet ne produit pas de fichier USDZ : pas de vue en réalité augmentée sur iPhone pour cet essai.
- Non vérifié : le fonctionnement de l'envoi de la photo et du téléchargement depuis un iPhone ; sur ordinateur
  c'est le fonctionnement normal de Colab.

## Licences (lues sur les sources officielles le 23 novembre 2026)

| Élément | Licence | Remarque |
|---|---|---|
| TripoSR, code et poids | MIT | code figé au commit `107cefd`, poids à la révision `5b52193` |
| DINO ViT-B/16 (encodeur d'image) | Apache-2.0 | seule sa configuration est téléchargée |
| rembg 2.0.69 (détourage) | MIT | modèle **U2-Net** (Apache-2.0), demandé par son nom |
| scikit-image, trimesh, einops, omegaconf, transformers | BSD / MIT / MIT / BSD / Apache-2.0 | |
| model-viewer (affichage 3D dans le carnet) | Apache-2.0 | chargé par le navigateur |

Volontairement **non utilisés**, bien que TripoSR les demande par défaut :
- `torchmcubes` (MPL-2.0, à compiler) : remplacé par scikit-image ;
- `imageio-ffmpeg` (contient un FFmpeg compilé sous GPL) : sert à une vidéo que le carnet ne fait pas ;
- le modèle de détourage que les versions récentes de rembg prennent par défaut, BRIA RMBG (non commercial).

Rien sous GPL ou AGPL, rien de non commercial. Deux paquets sous MPL-2.0 arrivent avec les outils installés
(`tqdm`, `certifi`) : tolérés comme dans le reste du projet, car ni modifiés ni redistribués.

## Pourquoi pas un modèle plus récent

D'après la lecture des dépôts officiels (la vérification contradictoire de cette liste a été interrompue et reste
à refaire avant toute décision) :

- **TRELLIS.2, Pixal3D** et leurs dérivés (2025-2026, code et poids MIT) : ne fonctionnent pas sans l'encodeur
  **DINOv3** de Meta, sous une licence propre à Meta (acceptation obligatoire, règles d'export, résiliation
  possible). Leur export GLB passe en plus par **nvdiffrast** de NVIDIA, réservé à la recherche et à l'évaluation.
- **TRELLIS** (première version) : encodeur DINOv2 (Apache-2.0), mais le même export GLB par nvdiffrast.
- **TripoSG, Hi3DGen, Direct3D-S2** (MIT) : la forme seule, sans couleurs.
- **Step1X-3D** (Apache-2.0) : son étape de texture reprend du code Tencent non commercial et nvdiffrast.
- **Hunyuan3D** (Tencent), **Stable Fast 3D / SPAR3D** (Stability), **SAM 3D** (Meta) : licences à conditions
  (exclusion de l'Union européenne, seuil de chiffre d'affaires, licence maison).

La décision qui ouvrirait les modèles récents est la vôtre : accepter ou non la licence DINOv3 de Meta. Il resterait
alors à remplacer l'export par nvdiffrast, ce qui est un travail de développement.
