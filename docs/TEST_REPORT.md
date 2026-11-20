# Rapport de test — DishPlay Scan P1 (16 novembre 2026)

Statut résumé : **la chaîne complète a été écrite, compilée et testée automatiquement ; elle n'a PAS encore été
essayée sur un iPhone ni sur un vrai plat.** Toutes les mesures de qualité ci‑dessous viennent de scènes
**synthétiques** de test (assiette creuse texturée + aliment, rendues par lancer de rayons) ; elles valident le
code, pas la qualité sur des aliments réels.

| Niveau | État |
|---|---|
| Écrit | backend, contrats, outils, app iOS, workflows, docs (ce dépôt, branche `main`) |
| Compilé | app iOS compilée pour iPhone (non signée) sur runner GitHub macOS‑15, Xcode 26.3 — `** BUILD SUCCEEDED **` ([run 43777985145](https://github.com/Omazi/dishplay3d/actions/runs/43777985145)) |
| Testé automatiquement | 34 tests Python (Linux, Python 3.12) + 11 tests Swift `ScanCore` (macOS) — tous passés |
| Testé sur appareil | **non** (pas d'accès à l'iPhone ni aux secrets de signature) |
| Distribué TestFlight | **envoyé et accepté par Apple** : 1.0.0 (6.1), Delivery UUID a60678d3-3862-4036-8343-df53091bdc32 ([run 43800091684](https://github.com/Omazi/dishplay3d/actions/runs/43800091684)) ; installation sur iPhone non encore confirmée |
| Qualité observée sur un vrai plat | **inconnue** à ce jour |

## Environnement de mesure
Conteneur Linux x86‑64, 4 vCPU, 16 Go, sans GPU ; Python 3.12.3 ; OpenCV 4.12.0 ; Open3D 0.19.0 (CPU).
Votre PC (8 Go évoqués) peut être plus lent ou plus rapide : `tools/doctor.py` mesure sur place.

## Boucle réseau réelle (test `test_server_e2e.py`)
Serveur lancé en processus séparé, HTTPS avec certificat auto‑signé **épinglé**, jumelage par code, client Python
qui parle exactement le protocole de l'app (enveloppes DPF1, WebSocket, géométrie DPG1). 60 vues synthétiques
640×480 envoyées à ~3 vues/s.

| Mesure | Résultat (dernier passage) | Cible du brief |
|---|---|---|
| Premier nuage reçu après la 1re vue envoyée | 4,5 s (3,0 s au passage précédent) | < 15 s |
| Mises à jour géométriques pendant la capture | 19 (dont points + surface partielle) | maillage avant « Terminer » |
| Intervalle entre mises à jour : médiane / P95 | 2,18 s / 2,71 s | 2–5 s |
| Vues intégrées | 60/60 (sous charge CPU concurrente : quelques vues « différées à la finition », statut explicite) | — |
| Finition (re‑stéréo, maillage, texture 2048², exports) | 55 s | — |
| Erreur d'échelle (largeur 24 cm) | < 5 % (assertion) ; −0,7 % au rejeu ci‑dessous | ≤ 5 % |
| Refus : mauvaise empreinte TLS, mauvais code, jeton absent (401), conflit d'ID de vue (409), chemin d'artefact `../` | tous refusés | — |

## Rejeu déterministe (90 vues, dérive de suivi simulée)
`tools/replay_session.py local … --finish` : 90/90 vues intégrées, 93/93 paires valides, résidu épipolaire médian
0,12 px ; latence réception→première version la contenant : médiane 0,4 s, P95 0,8 s (horloge de capture
rejouée) ; ~1,1–1,5 s de calcul par vue sur 4 cœurs. Finition : 63 449 triangles, 96 % des sommets « mesurés »,
4 % « interpolés », 0 « estimé » ; texture OK (24 vues) ; largeur −0,68 %.
Image : `docs/evidence/synthetic_progression.png` (v1 après 3 vues, v6, v29 avant Terminer, finition).

## Précision géométrique (synthétique, 640×480, f = 500 px, ~0,4 m)
- Profondeur par paire : erreur médiane 0,7–1,9 mm, P95 < 12 mm (assertion).
- Nuage live fusionné : médiane ~2 mm, P90 ~5–7 mm. Surface live : médiane ~0,8–1,2 mm.
- Finition 1280×960 : médiane 0,6 mm, P90 3,4 mm.
- **Creux préservé** : fond du puits mesuré 8,3–8,6 mm pour 8 mm réels ; rebord ~21 mm pour 22 mm (test dédié).
- **Zones non vues** : avec un tiers de tour, 98 % des sommets sont à < 8 mm d'une surface réellement vue (test).
- **Assiette blanche unie** : les pixels sans texture sont laissés inconnus (test) — sur un vrai plat blanc, attendez-vous
  à des trous plutôt qu'à des surfaces inventées.
- Biais connu : léger « grossissement » des bords en live (+3–4 % de largeur au rejeu live), réduit à ~±1 % en finition.

## Constats et décisions pendant le développement
- Bug corrigé : ordre des dimensions de la boîte incohérent entre deux fonctions → seule une bande de l'assiette
  était reconstruite. Convention unique désormais : (largeur x, hauteur y, profondeur z), testée.
- Plage de disparité serrée sur les correspondances SIFT → faux appariements ; remplacée par la plage issue de la
  boîte, rétrécie seulement si nécessaire, et rejet des disparités saturées.
- Alignement ICP de chaque vue sur le modèle (compensation de dérive) : **mesuré défavorable** sur les données
  synthétiques (P90 7,5 mm contre 5,1 mm sans) → livré désactivé (`align_to_model=False`).
- Ajustement de faisceaux global : **non réalisé** en P1 (correction de pose relative par paire seulement).
- Haute résolution `captureHighResolutionFrame` : **non utilisée** ; l'app envoie l'image native 1920×1440 de chaque
  vue clé, et la finition la retraite à 960 px de large (réglable).

## Mise à jour du 16 novembre (soir) — premier scan réel et qualité 3D

**Premier scan réel (iPhone 13, bol de noix, de nuit)** : la chaîne a fonctionné de bout en bout (255 vues envoyées,
50 versions en direct, finition). Défauts observés sur les captures de l'utilisateur : noix floues, bord du bol
déchiqueté, lambeaux flottants, guidage difficile à suivre. Le dossier de session n'a pas été transmis : les
réglages ci-dessous n'ont donc **pas** été vérifiés sur ces données réelles.

**Banc d'essai plus dur** (`tools/bench_quality.py`, scène `tests/realistic.py`) : bol profond à bord fin, parois
presque unies, tas de petits objets, trajectoire à la main, dérive du suivi, bruit, flou de mouvement. Il reproduit
les défauts du scan réel. Mesures après recalage rigide (la dérive simulée décale tout le modèle de ~4 mm) :

| Mesure (modèle final) | Avant | Après |
|---|---|---|
| Fragments éloignés (> 15 mm de la vraie surface) | 2,6 % | 0 % |
| Parois du bol reconstruites | 24 % | 77 % (signalées « interpolé ») |
| Bord du bol reconstruit | 95 % | 99 % |
| Petits objets (noix) reconstruits | 65 % | 78 % |
| Couverture globale des surfaces vues | 59 % | 84 % |
| Précision des surfaces « mesurées » (P90) | 3,7 mm (tout confondu) | 3,2 mm |
| Précision des surfaces « interpolées » (P90) | — | 5,2 mm |

Image : `docs/evidence/qualite_avant_apres.png`.

**Ce qui a changé dans le moteur**
- *Confirmation multi-vues* (`reconstruction/consistency.py`) : une profondeur n'est fusionnée que si d'autres vues,
  avec leur propre carte de profondeur, voient la même chose au même endroit et de la même couleur, et si elles sont
  majoritaires. Une vue qui « voit à travers » le point le contredit. La fusion d'une vue attend 2 vues suivantes en
  direct (4 en finition).
- *Texture faible* : constat mesuré — sur une paroi quasi unie, ~30 % seulement des profondeurs brutes sont justes et
  l'appariement interpole entre le bord et le fond. Ces surfaces ne sont plus jetées ni présentées comme mesurées :
  elles sont conservées si elles sont confirmées, et classées **interpolées** (bleutées à l'écran, `_PROVENANCE = 1`
  dans le GLB).
- Contraste local normalisé avant l'appariement ; passe demi-résolution en finition ; troncature TSDF plus courte et
  voxels de 2,5 mm en direct ; suppression des îlots détachés ; paires stéréo un peu plus écartées.
- Vitesse : la vérification de pose (RANSAC) prenait plus de la moitié du temps par vue ; elle est bornée.
  Mesuré ici : ~0,37 s par vue en direct (4 cœurs, 640 px).
- Chaque finition écrit `final/apercu.png` (4 vues du modèle) pour juger ou partager le résultat d'un coup d'œil.

**Limites qui restent**
- Les surfaces sans texture (plastique uni, assiette blanche) ne sont pas *mesurées* par cette stéréo classique :
  elles sont interpolées et signalées, avec une erreur de l'ordre de 5 mm sur le banc. Les mesurer vraiment
  demanderait une autre source (LiDAR, lumière structurée, ou un modèle appris à auditer).
- Pas de recalage global des poses : la dérive du suivi décale le modèle entier (≈4 mm sur le banc).
- Toujours aucune mesure de qualité sur données réelles.

**App iPhone** (compilée en CI, non vérifiée par moi sur appareil) : 1.2.x — guide en anneau, aperçu qui suit le
téléphone, boîte accrochée à un repère ARKit, exposition fixe et obturateur ≤ 1/100 s pendant le scan ; 1.3.0 —
reprise d'un scan interrompu (envoi des vues restantes puis finition).

## Mise à jour du 16 novembre (nuit) — lacunes traitées une par une

Mesures sur le banc `tools/bench_quality.py` (bol synthétique, deux tirages aléatoires), 38 tests automatiques passés.
Rien de ceci n'est vérifié sur un vrai plat.

| # | Lacune | État | Ce qui a été fait / mesuré |
|---|---|---|---|
| 1 | Surfaces unies non mesurées | **non corrigeable par cette méthode** | Elles restent interpolées et signalées (bleu, `_PROVENANCE = 1`), erreur P90 ≈ 4–5 mm sur le banc. Les mesurer demande une autre source (LiDAR : chemin codé, jamais testé). |
| 2 | Brillant | **partiel** | Les reflets saturés (≥ 250/255) et leur bord sont exclus du calcul de profondeur (test dédié). Les reflets non saturés et le transparent ne sont pas traités. |
| 3 | Détail fin | **partiel** | Finition à 1152 px de large (au lieu de 960), aperçu en direct jusqu'à 100 000 points / 60 000 triangles. Effet non mesurable sur le banc (images 640 px). `captureHighResolutionFrame` toujours non utilisé. |
| 4 | Dérive du suivi | **corrigé en finition** | Recalage global des poses (`reconstruction/bundle.py`, ajustement de faisceaux sur traces SIFT, liens fermes aux mouvements ARKit consécutifs, première caméra fixe). Erreur de position des caméras 3,9 → 1,6 mm (médiane) ; décalage global du modèle 3,5 → 2,3 mm et 0,6 mm selon le tirage. Appliqué seulement s'il réduit l'erreur de reprojection et reste proche d'ARKit ; sinon poses ARKit conservées (`report.json › pose_refinement`). ~22 s pour 110 vues. Pas appliqué à l'aperçu en direct. |
| 5 | Dessous / zones cachées | **par conception** | Rien n'est inventé. Ajout : `final/plat_seul.glb`, le même modèle sans la table autour du plat (rien d'ajouté, dessous ouvert). Base estimée : non faite, décision produit. |
| 6 | Texture finale jamais vérifiée | **2 défauts trouvés et corrigés** | (a) la texture était retournée verticalement dans le GLB (convention glTF) ; (b) ~30 % de la surface restait noire. Désormais 36 vues projetées, zones non couvertes remplies par la couleur fusionnée ; contrôle automatique : < 0,1 % de noir, erreur de couleur moyenne ≈ 11/255 lue comme un visualiseur glTF. |
| 7 | Aucun réglage sur données réelles | **outillé, en attente** | `tools/pack_session.py` produit un zip compact (≈ 6 Mo pour 110 vues) rejouable tel quel ; `final/apercu.png` écrit à chaque finition. |

## Mise à jour du 16 novembre (après le deuxième scan réel) — surface froissée, points flottants

Constat sur les captures d'écran de l'utilisateur (assiette à motifs sur parquet, aperçu en direct, 120 vues) :
forme reconnaissable (rebord, creux, tache de sauce) mais surface froissée partout, y compris sur le parquet pourtant
bien texturé, et points bleus flottants au-dessus du plat. Je n'ai pas les données de cette session, seulement les images.

Hypothèse testée : un petit bruit indépendant d'une vue à l'autre sur les positions données par le suivi
(`tools/bench_quality.py --jitter-mm 0.6 --jitter-deg 0.06`). Il reproduit le défaut sur le banc. Cause mesurée : la
profondeur d'une paire est proportionnelle à la longueur de sa base ; 0,85 mm d'erreur sur 35 mm déplace toute la carte
de profondeur de ~2,4 %, soit ~8 mm à 33 cm. **L'amplitude réelle du bruit ARKit n'est pas connue** : ce niveau est un
choix qui reproduit l'aspect observé, pas une mesure sur l'iPhone.

Corrections (moteur `p1-0.2.0`, 40 tests passés) :
1. `consistency.depth_scale_from_views` : chaque carte de profondeur est remise à l'échelle (un seul nombre) pour
   s'accorder avec les vues voisines déjà acceptées, à 80 % seulement pour que l'échelle moyenne reste celle du suivi.
2. Lissage de Taubin (10 itérations, positions seulement) du maillage d'aperçu et du maillage final.
3. Les points affichés à plus de 3 mm de la surface fusionnée sont masqués (comptés dans `hidden_inconsistent_points`,
   conservés dans `points.ply`).

| Banc, bol synthétique, 110 vues | Avant | Après |
|---|---|---|
| **Aperçu en direct, avec bruit de pose** — surface couverte | 61,9 % | 71,2 % |
| — bord du bol reconstruit | 26,2 % | 81,6 % |
| — parois du bol | 38,5 % | 50,9 % |
| — erreur P90 / fragments > 6 mm | 3,4 mm / 3,2 % | 3,9 mm / 2,5 % |
| — rugosité (angle médian face/sommet) | 11,8° | 7,2° |
| — points affichés à > 6 mm de la vraie surface | 18,3 % | 2,3 % |
| Aperçu en direct, sans bruit — surface / bord / parois | 75,2 / 99,7 / 55,9 % | 76,4 / 98,6 / 60,4 % |
| **Modèle final, avec bruit** — surface / bord / parois | 77,7 / 99,3 / 65,5 % | 77,9 / 99,3 / 65,7 % |
| — erreur médiane / P90 | 1,13 / 4,45 mm | 0,94 / 4,38 mm |
| Modèle final, sans bruit — surface / parois / P90 | 83,1 / 75,3 % / 4,35 mm | 81,6 / 72,9 % / 4,20 mm |
| Coût de l'aperçu (110 vues, une exécution seule) | 69,8 s | 73,9 s |

Lecture honnête : le gain est net sur l'aperçu en direct quand les poses tremblent ; le modèle final, déjà protégé par
le recalage global, ne change presque pas (léger recul de couverture sans bruit, −1,5 point). L'erreur P90 de l'aperçu
monte de 0,5 mm parce que la surface reconstruite est plus étendue. Image : `docs/evidence/tremblement_avant_apres.png`.

Non traité dans cette passe : motifs fins de l'assiette absents de l'aperçu en direct (couleur par voxel de 2,5 mm ; la
texture n'est calculée qu'à la finition), trous sur la sauce brillante, table affichée avec le plat dans l'aperçu.

## Mise à jour du 16 novembre — premières vraies captures iPhone rejouées dans le moteur

Jusqu'ici tous les réglages venaient de scènes de synthèse. `tools/import_objectron.py` convertit une capture du jeu
public Objectron (vidéo iPhone tenue à la main, poses ARKit réelles, boîte 3D annotée) en session rejouable. Trois
captures de la catégorie « cup » ont été rejouées (aperçu + finition). Les données ne sont pas dans le dépôt.
Limites : ce ne sont pas des plats, la vidéo est compressée (H.264) et le tour autour de l'objet est partiel (≈ 9 s).

Défaut trouvé, invisible en synthèse : les points d'intérêt n'étaient cherchés que dans la boîte ; sur de vraies images
il y en a trop peu, et une paire sans assez de correspondances était **rejetée** au lieu d'utiliser la pose ARKit.

| Gobelet métal, 89 vues | Avant | Après |
|---|---|---|
| Paires d'images acceptées (aperçu) | 53 / 338 | 96 / 113 |
| Vues intégrées à l'aperçu | 51 | 88 |
| Vues intégrées au modèle final | 34 | 89 |
| Paires acceptées en finition | 49 / 320 | 185 / 195 |

Correction : détection sur toute l'image ; si la pose ne peut pas être vérifiée faute de correspondances, elle est
utilisée telle quelle (`pose_source = arkit_unverified`) et la profondeur doit toujours passer le contrôle
gauche-droite et la confirmation par d'autres vues. 40 tests passés, banc synthétique inchangé.

Résultat visuel, sans complaisance : table complète, formes reconnaissables (pied et bord du gobelet, bord et anse de la
tasse), mais corps brillants ou unis absents ou troués, surfaces grossières. **Ce n'est pas un rendu de qualité
produit.** La méthode (paires d'images à 640–1152 px, appariement par blocs) plafonne sur le brillant et l'uni.

## Mise à jour du 16 novembre — préparation d'un essai de reconstruction neuronale

Décision : la méthode par paires d'images plafonne sur la nourriture (brillant, uni, translucide). Essai prévu d'une
reconstruction par Gaussian splatting sur le PC de l'utilisateur (GTX 1650, 4 Go), voir `docs/ESSAI_NEURONAL.md`.
- `tools/export_splat_dataset.py` : session → jeu de données au format Nerfstudio (images, masques de la boîte,
  caméras dans le repère de la boîte, points initiaux). La finition écrit désormais `final/poses.json` (poses affinées).
- Vérifié : test automatique (les coins de la boîte se projettent au même pixel, à 0,05 px près, avec la convention
  exportée et avec celle du moteur) ; sur une vraie capture, 99,6 % des points du modèle retombent dans les masques.
- **Non exécuté : l'entraînement lui-même** (pas de carte graphique dans l'environnement de développement).

## Mise à jour du 16 novembre — étape neurale automatique dans le calculateur

Après « Terminer » et la livraison du modèle classique, le calculateur lance tout seul la reconstruction neuronale
(`reconstruction/neural.py`) **si** la machine a une carte NVIDIA avec PyTorch et gsplat. Sinon rien ne change.
Sorties ajoutées au dossier `final/` : `splat.ply`, `turntable.mp4`, `neural_compare.jpg`, `neural_report.json`.
- Vérifié : 42 tests ; mécanique complète (export, boucle, évaluation, fichiers, événements de progression) sur
  processeur avec un rendu factice à la place de la carte graphique.
- **Non vérifié : le rendu réel sur carte graphique** (aucune disponible) ; l'app n'affiche pas encore ces fichiers.

## Mise à jour du 16 novembre — la table autour du plat n'est plus dans le modèle (moteur `p1-0.3.0`)

La boîte de scan est rectangulaire, une assiette est ronde : les coins de la boîte contiennent de la table nue.
`mesh_preview.DishFootprint` repère l'emprise du plat (zone où le modèle s'élève au-dessus de la table, table ajustée
comme un plan à partir des données) et retire la couche de table en dehors, ainsi qu'un liseré de 1 cm sous le bord.
Appliqué à l'aperçu en direct, au modèle final (`model.glb` = plat seul ; `model_avec_table.glb` gardé à côté) et à
l'étape neurale (masques et découpe suivent l'emprise). Rien n'est ajouté ni refermé.
- Vérifié : 43 tests (dont table décalée de −6 à +7 mm par rapport à la base de la boîte, contour qui suit
  l'assiette ronde) ; assiette de synthèse (`docs/evidence/table_retiree_assiette.png`) ; trois vraies captures
  iPhone du jeu public (triangles gardés : 34 %, 34 % et 16 % du maillage, le reste étant de la table).
- Limites : un aliment plat de moins de 6 mm posé directement sur la table serait pris pour la table ; pas vérifié
  sur un vrai plat scanné par l'utilisateur.

## Mise à jour du 16 novembre — finition trop longue sur un long scan

Constat utilisateur : 272 vues, finition affichée « 165/272 » une vingtaine de minutes après « Terminer », perçue
comme bloquée. Rien n'indique un blocage : la finition traitait toutes les vues, la progression ne s'affichait que
toutes les 5 vues et sans durée restante.

Corrections : la finition travaille sur au plus 140 vues réparties autour du plat (`refinement.spread_subset`,
choix par éloignement mutuel des positions de caméra) ; progression émise à chaque vue ; le choix des paires ne
charge plus toutes les images (géométrie lue dans les métadonnées, cache d'images réduit à 96) ; l'app affiche le
temps restant estimé (1.4.3).

| Vraie capture iPhone du jeu public, 245 vues, finition sans texture, même machine (4 cœurs) | Toutes les vues | 140 vues |
|---|---|---|
| Durée de la finition | 383 s | 219 s |
| Vues intégrées | 229 | 140 |
| Triangles du modèle | 26 146 | 21 267 |
| Mémoire maximale | 1,6 Go | 1,5 Go |

Lecture honnête : −43 % de temps, pour un modèle un peu moins dense. Sur le PC de l'utilisateur (environ 7 s par
vue d'après sa capture d'écran, contre 1,6 s ici), 140 vues représentent encore de l'ordre d'un quart d'heure : la
durée reste liée à la puissance du processeur. 44 tests passés.

## Mise à jour du 16 novembre — verdict de qualité pendant le scan (moteur `p1-0.4.0`, app 1.6.0)

Besoin exprimé : savoir avant « Terminer » si le scan donnera un bon modèle. L'anneau ne mesure que les directions
vues. `reconstruction/quality.py` juge le modèle lui-même : couverture vue de dessus, morcellement de la surface
(longueur des bords ouverts rapportée à l'aire), part réellement mesurée, côtés vus, nombre de vues utiles.
Le verdict (`good` / `fair` / `poor` + causes) est envoyé avec chaque aperçu ; l'app l'affiche et prévient avant de
terminer un scan insuffisant.

| Cas | Verdict | Ce que je vois sur le rendu |
|---|---|---|
| Assiette de synthèse texturée, tour complet | good (97) | complète |
| Bol de synthèse uni | fair (90), surface unie | parois partiellement interpolées |
| Vraie capture, tasse (tour partiel) | poor (56) : morcelé, côtés manquants, trous | corps absent |
| Vraie capture, gobelet métal | poor (68) : morcelé, trous | parois absentes |
| Vraie capture, gobelet rouge (tour partiel) | poor (68) : morcelé, côtés manquants | incomplet |

Limites : seuils calés sur ces cinq cas seulement, aucun vrai plat ; un premier jeu de seuils avait classé « good » le
gobelet métal (vu de dessus il paraît complet), d'où l'ajout du morcellement. Le verdict porte sur l'aperçu en direct,
pas sur le modèle final. Côté app : écrit mais **non compilé** (GitHub Actions bloqué par le quota du compte).

## Mise à jour du 16 novembre — surfaces unies ou brillantes : remplissage par profondeur apprise (moteur `p1-0.5.0`)

Besoin exprimé : le restaurateur choisit son plat, le moteur ne peut pas demander d'éviter le blanc uni ou le
brillant. La stéréo ne mesure que là où il y a un motif ; ailleurs elle laisse un trou. Ajout :
`reconstruction/mono_depth.py`. Un réseau de profondeur à une image (Depth Anything V2 Small, ONNX, Apache-2.0,
99 Mo, processeur seul) prédit la forme relative de chaque vue ; cette prédiction est recalée sur les profondeurs
que la stéréo a mesurées dans la même vue (droite robuste en profondeur inverse, puis correction locale lissée),
et seuls les pixels de la boîte restés vides sont remplis. Ces pixels passent ensuite la même confirmation par
les autres vues que le reste, et sont classés « interpolé », jamais « mesuré ». Garde-fous : prédiction rejetée
si elle s'écarte de plus de 4 % des mesures de la vue ; rien n'est posé sur un saut de profondeur ; sans le fichier
du modèle ou sans `onnxruntime`, le moteur se comporte exactement comme avant. Activé à la finition ; pendant la
capture seulement sur demande (`mono_live`), faute de mesure du temps par vue.

**Ce qui est vérifié, et avec quoi.** Le vrai réseau n'a **pas** été exécuté : dans cette session, l'installation
d'`onnxruntime` et l'exécution du modèle téléchargé ont été refusées deux fois par la protection automatique.
Tout ce qui suit utilise un **remplaçant simulé** (`OracleMono`) : la vraie profondeur de la vue de synthèse,
abîmée comme un réseau se trompe (échelle et décalage inconnus, déformation lente de 3 %, bruit). Cela mesure ce
que l'étape de remplissage fait d'une prédiction de cette qualité — une borne haute, pas le résultat du vrai réseau.

Bol de synthèse uni, 110 vues, images dégradées, dérive de suivi (`tools/bench_quality.py`, avec et sans
`--mono-oracle`) :

| | Sans | Avec (simulé) |
|---|---|---|
| Parois du bol couvertes, aperçu en direct | 65,9 % | 98,5 % |
| Parois du bol couvertes, modèle final | 80,0 % | 97,5 % |
| Couverture totale, modèle final | 84,6 % | 92,1 % |
| Précision p90, modèle final | 4,12 mm | 3,34 mm |
| Sommets à plus de 6 mm, modèle final | 3,24 % | 0,92 % |
| Part des pixels remplis gardés après confirmation par les autres vues | — | 35 % |

Trou seul (180 × 140 px sans aucune mesure, une vue) : erreur médiane du remplissage 0,3 mm avec une prédiction
parfaite à l'échelle près, 1,4 mm à 3 % de déformation, 2,6 mm à 6 %, 4,7 mm à 12 % — la précision loin des
mesures suit directement celle du réseau, d'où la confirmation par les autres vues.

Limites : aucune image réelle, aucun vrai plat, vitesse du réseau sur le PC non mesurée, comportement réel sur
reflets et sauces inconnu. Une vue sans aucune profondeur stéréo (assiette blanche sur nappe blanche) ne peut pas
être recalée et reste vide. Premier vrai essai : sur le PC, après mise à jour (`start-calculator.ps1` installe la
bibliothèque et télécharge le modèle, somme SHA-256 vérifiée ; `DISHPLAY_MONO=0` pour s'en passer) ;
`final/report.json` → `mono_fill` dit combien de vues ont été remplies, combien de pixels gardés, et le temps passé.
51 tests passés, 1 sauté (celui du vrai réseau, absent ici). Script Windows modifié mais non exécuté (pas de PowerShell ici).

## Mise à jour du 17 novembre — travail sur de vraies captures d'iPhone (moteur `p1-0.6.0`)

Changement de méthode : diagnostic étape par étape sur de vraies captures (Objectron, tasses filmées à l'iPhone
avec poses ARKit), plus sur la synthèse. Faute de modèle de référence, deux mesures objectives : la table est
plane (dispersion de ses points autour d'un plan = erreur géométrique entre vues) et le morcellement de la surface.

**Constats mesurés (tasse noire, 41 vues, finition).**
- Une paire d'images ne donne une profondeur que sur ~1/3 de la zone de la boîte : l'appariement par blocs refuse
  les surfaces unies. Ni la plage de recherche, ni le recouvrement des images, ni le rognage à la boîte n'en sont
  la cause (vérifiés un par un). Le mode 8 directions et un bloc plus grand n'apportent que 1,59 → 1,39 mm de bruit.
- Deux paires d'une même vue diffèrent de plusieurs % de façon lisse : la table est inclinée de 1,9° en médiane
  (jusqu'à 8°) d'une paire à l'autre. Cause : erreur de pose relative (suivi, obturateur déroulant), ≈ 1 px de
  disparité. Le moteur supprimait le désaccord au lieu de corriger le biais.

**Correction** (`consistency.depth_bias_from_views`) : le biais de chaque paire (échelle, décalage, inclinaison en
profondeur inverse) est estimé contre les vues acceptées et retiré avant la comparaison des paires. Un premier
ajustement par moindres carrés était mal conditionné sur une table vue de biais (corrections fantômes de 11 % sur
le bol de synthèse, bord du bol 99 → 91 %) ; stabilisé par une régularisation sur colonnes normalisées.

| | Avant | Après |
|---|---|---|
| Gobelet réel : dispersion de la table | 1,35 mm | 0,37 mm |
| Gobelet réel : morcellement | 46,2 | 22,3 |
| Gobelet réel : surface au-dessus de la table | 283 cm² | 390 cm² |
| Tasse réelle : dispersion / morcellement | 1,67 mm / 30,1 | 1,26 mm / 27,1 |
| Bol de synthèse, modèle final : bord / parois / précision p90 | 99,2 % / 80,0 % / 4,12 mm | 99,4 % / 79,8 % / 4,22 mm |

**Fermeture de la surface** (`closure.py`, Poisson d'Open3D) : rustines étiquetées « estimé » sur les trous et base
plate sous le plat ; les sommets reconstruits ne sont pas modifiés ; `model_mesure.glb` garde le modèle tel que
reconstruit. Réglage généreux (3 cm) : enveloppe gonflée autour de l'objet sur la capture réelle — rejeté. Réglage
retenu (8 mm) : ne bouche que les petits trous. Sur le bol de synthèse, les sommets estimés sont à 1,9 mm (médiane)
de la vraie forme, p90 4,4 mm. **Les grands trous restent** : sur ces captures les deux tiers de la zone ne sont pas
mesurés, et cela ne se rebouche pas proprement après coup.

**App** : les zones interpolées ou estimées gardent leurs vraies couleurs ; la teinte bleue devient une option des
Réglages. Écrit, **non compilé**.

Limites : deux captures réelles seulement, des tasses (noire brillante, rouge), aucun plat ; le remplissage par
profondeur apprise n'a toujours pas tourné sur de vraies images. 63 tests passés, 1 sauté.

## Mise à jour du 17 novembre (suite) — le contrôle aller-retour perdait les côtés de l'image (moteur `p1-0.6.1`)

Suite du diagnostic sur vraies captures : pourquoi une paire ne donne une profondeur que sur un tiers de la boîte.
Écartés par la mesure : seuil d'unicité (0, 3 ou 8 : aucun effet), tolérance aller-retour (1 → 1,5 px : aucun
effet), images plus détaillées (1920 px : aucun gain). Regardé paire par paire : l'appariement brut répond sur 65 à
72 % de la zone, puis le contrôle aller-retour en supprime 27 à 49 %. Les vrais désaccords ne font que 4 à 6 % ;
le reste vient de ce que la carte « retour » n'a pas de valeur dans une bande aussi large que la plus grande
disparité cherchée (200 à 360 px), l'appariement ne pouvant pas explorer le bord de son image de gauche.
Correction : les deux images sont élargies d'autant avant l'appariement, puis recoupées.

| | Avant | Après |
|---|---|---|
| Test dédié : pixels vus par les deux images et validés | 78 % | > 95 % |
| Tasse réelle : part de la boîte avec profondeur, par paire | 33 % | 52 % |
| Tasse réelle, modèle final reconstruit : surface / morcellement | 646 cm² / 27,1 | 689 cm² / 23,7 |
| Gobelet réel, modèle final reconstruit : surface / morcellement | 691 cm² / 22,3 | 702 cm² / 21,2 |
| Bol de synthèse, final : bord / parois / points à > 6 mm | 99,3 % / 80,6 % / 3,0 % | 99,4 % / 78,9 % / 3,0 % |

Le gain par paire (+58 %) ne se retrouve que partiellement dans le modèle final (+2 à +7 % de surface) : avec 80
vues et trois paires par vue, d'autres paires couvraient déjà ces zones ; il doit surtout profiter à l'aperçu en
direct, qui a moins de vues (non mesuré). Ce qui manque encore sur ces objets (intérieur blanc, corps noir
brillant) n'est mesuré par aucune paire. Rendu en vraies couleurs : `docs/evidence/tasses_reelles_avant_apres.jpg`.
64 tests passés, 1 sauté.

## Mise à jour du 17 novembre (soir) — objets texturés réels : toutes les vues étaient écartées (moteur `p1-0.6.2`)

Essai sur des captures réelles d'objets texturés (Objectron : livre, paire de chaussures, boîtes imprimées), plus
proches d'un plat garni que les tasses. Résultat initial : 0 vue utilisée sur 94 pour le livre, 10 sur 85 pour les
chaussures. Cause mesurée : la sélection des paires exigeait que chaque vue montre 60 % de la boîte ; à 26–31 cm
d'une boîte de 53 ou 64 cm, aucune vue ne le fait (visibilité médiane 0,36 et 0,41), alors que des centaines de
paires avaient une géométrie correcte. Les vues restaient « en attente de partenaire », sans message.
Correction : la vue de référence doit montrer une partie de la boîte (12 %) et le partenaire voir 60 % de ce que
la référence voit.

| | Avant | Après |
|---|---|---|
| Livre : vues utilisées | 0 / 94 | toutes (essai sur 32) |
| Chaussures : vues utilisées / surface reconstruite | 10 / 85 — 865 cm² | 81 / 85 — 1 863 cm² |
| Boîtes imprimées | 67 / 75 vues | faces vues complètes, impression lisible |

Conséquence probable pour les scans de l'app (non vérifiée, je n'ai aucun de ces scans) : une assiette de 28–30 cm
filmée à 25–30 cm est dans le même cas.

Ce qui reste, constaté sur le livre : sa couverture rouge unie ne reçoit aucune profondeur (appariement brut
compris). Le remplissage par profondeur apprise, prévu pour ce cas, n'a pas pu être exécuté ici (installation
refusée par la protection de la session, trois fois). 66 tests passés, 1 sauté.

## Mise à jour du 17 novembre (nuit) — le fichier 3D texturé vu comme sur le site (moteur `p1-0.6.3`)

Contrôle de bout en bout sur deux captures réelles d'objets texturés : finition complète (table retirée, texture
photo), puis `model.glb` affiché dans un navigateur par model-viewer (Apache-2.0), captures d'écran dans
`docs/evidence/objets_textures_reels_glb.jpg`.

- Boîtes imprimées : faces vues complètes, impression nette et lisible, bords irréguliers, un reste d'étagère.
- Paire de chaussures : reconnaissable et texturée du côté scanné (lacets, tissu, logo) ; côtés non scannés absents,
  morceaux du décor voisin conservés (la boîte faisait 2,2 fois l'objet).
- Défaut trouvé : sur les chaussures, la texture photo échouait (« UVAtlasPartition: Non-manifold ») et le modèle
  retombait sans le dire sur les couleurs par sommet. Cause : une arête partagée par trois triangles, venue des
  rustines de fermeture. Corrigé (rustines filtrées, garde avant l'atlas), avec tests.
- Constat produit : `model.glb` des chaussures pèse 25 Mo (112 000 triangles, texture PNG 2048) — trop lourd pour
  un menu en ligne ; allègement à faire.

Jugement honnête : sur un objet texturé, le résultat est maintenant un vrai modèle reconnaissable, ce qui n'était
pas le cas ce matin ; il n'a pas la propreté d'un produit du commerce (bords, fragments, zones unies vides).
33 tests des modules touchés passés ; suite complète précédente : 66 passés, 1 sauté.

## Mise à jour du 18 novembre — le modèle livré : contour propre, fichier léger, texture pleine résolution (moteur `p1-0.7.0`)

`reconstruction/delivery.py` et l'étape de texture de la finition. Vérifié sur deux captures réelles en affichant
`model.glb` dans un navigateur (model-viewer), avant et après : `docs/evidence/livraison_web_objets_reels.jpg`.

| | Avant | Après |
|---|---|---|
| Boîtes imprimées : poids de `model.glb` | 12,8 Mo | 2,8 Mo |
| Chaussures : poids de `model.glb` | 25,6 Mo | 3,4 Mo |
| Triangles livrés | 71 000 / 167 000 | 60 000 / 60 000 |
| Source de la texture | images réduites à 1152 px | photos d'origine, 1920 px |
| Format de la texture | PNG | JPEG qualité 88 |

- Gros plan dans le navigateur : même netteté de lecture des marques après allègement.
- Défaut trouvé à l'affichage : un liseré de la couleur du fond autour de chaque trou refermé. Vérifié en changeant
  la couleur de la page : c'était une fente entre la rustine et la surface. Les rustines chevauchent maintenant le
  bord du trou (test dédié).
- Contour : les dents et languettes d'un triangle de large sont retirées (843 et 2 831 triangles), les morceaux de
  moins de 2 % de la surface aussi. Les gros morceaux de décor voisins (linge à côté des chaussures) restent : ce
  sont de vrais objets dans la boîte, pas des débris.
- Le maillage complet reste disponible (`mesh.ply`, `model_vertexcolor.glb`, `model_mesure.glb`).

Limites inchangées : surfaces unies non mesurées ; aucun plat réel ; remplissage par profondeur apprise non exécuté.
73 tests passés, 1 sauté.

## Mise à jour du 20 novembre — positions des photos, objets plats, vignettes, relecture de l'app (moteur `p1-0.8.0`)

Point de départ : rejouer de vraies captures « en direct », finir une capture de livre (plat, couverture unie : le
plus proche d'une assiette) et faire relire l'app. Le livre sortait bosselé et à moitié découpé.

**Recalage des positions des photos (`bundle.py`).** Sur le livre (erreur de départ 5,2 px), le recalage s'arrêtait
après ses 40 étapes à 1,09 px, loin d'avoir convergé, et les liens très fermes avec le suivi de l'iPhone l'en
empêchaient (0,72 px après 300 étapes ; 0,35 px en 120 étapes avec des liens plus souples). Ajout d'une seconde
étape à liens plus souples, seulement quand la première laisse plus de 0,5 px et qu'assez de points tiennent les
caméras (300 observations par vue). Garde-fous, chacun né d'un défaut constaté :
- le réglage le plus souple n'est gardé que s'il reste près du suivi ; sinon un réglage intermédiaire, sinon la
  première étape (sur des boîtes en rayon, scène plane, il s'éloignait de 84 mm et tout le recalage était alors
  jeté : mesures confirmées 58 % → 42 %) ;
- la trajectoire affinée est superposée à celle du suivi dans son ensemble (position, orientation, taille), au
  lieu d'être accrochée à la première photo : sinon le modèle héritait de l'erreur de cette photo (2° sur le
  livre) et sa taille flottait de 1 à 2,5 %.

Juge indépendant des points suivis par le recalage : l'accord entre les cartes de profondeur denses.

| Capture réelle | Erreur de recalage | Mesures confirmées | Contredites | Correction lisse par paire |
|---|---|---|---|---|
| Chaussures, 85 vues | 0,90 → 0,16 px | 76,8 → 90,0 % | 12,4 → 3,4 % | 2,78 → 0,08 % |
| Livre, 94 vues, même boîte | 1,09 → 0,34 px | 51,7 → 57,3 % | 22,6 → 18,7 % | — → 0,19 % |
| Boîtes imprimées, 38 vues (avant le dernier garde-fou) | 1,23 → 0,20 px | 58,2 → 77,4 % | 27,5 → 11,6 % | 2,17 → 0,71 % |

Sur des vues de synthèse aux positions connues (bruit de suivi 1,5 mm / 0,15°) : erreur de position 2,44 mm
(suivi brut), 0,86 mm (première étape), **1,79 mm si on pousse la première étape à 160 pas** (une erreur de
recalage plus faible n'est donc pas une preuve), 0,69 mm avec la seconde étape. Coût : +24 s sur les chaussures,
+3 min sur le livre. Images : `docs/evidence/chaussures_avant_apres_recalage.jpg`,
`docs/evidence/livre_avant_apres_meme_boite.jpg`.

**Retrait de la table.** Sur le livre posé sur un lit, le niveau « table » était ajusté au milieu du support :
30 % des sommets en dessous (1 à 3 % sur de vraies tables). À boîte égale, l'ancien moteur plaçait la table à
15,9 mm et supprimait 54 885 triangles sur environ 58 000 : il restait deux lambeaux. Règle ajoutée : si plus de
10 % de la surface est sous le niveau trouvé, rien n'est retiré. Conséquence corrigée dans la foulée : sans table
reconnue, le verdict de qualité restait « trop tôt » pendant tout le scan ; il se calcule alors sur le contour du
modèle lui-même.

**Aussi dans cette version.** `apercu.png` (dont l'app tire la vignette du plat) : plat en grand, vraies couleurs,
sans texte technique (`docs/evidence/vignettes_avant_apres.jpg`) ; la vue d'ingénieur reste disponible
(`--diagnostic`). La base ajoutée sous le plat prend sa couleur unie au lieu des stries projetées par des vues
rasantes.

**Hypothèses écartées par la mesure.** Déformation de l'objectif : le coefficient estimé change de signe d'une
capture à l'autre (−0,007, +0,009, +0,002, +0,06). Lisser les cartes de profondeur ou le maillage : sans effet
sur l'ondulation du livre, qui venait des positions et non d'un bruit fin. Ma règle « la couverture est plane »
était elle-même fausse à 3 mm près (livre souple), d'où le recours à l'accord entre vues comme juge.

**Constaté, non corrigé.** En direct (sans recalage global), 39 à 41 % des mesures sont contredites sur les
captures texturées. Les aplats unis de la couverture restent des trous. Une boîte de scan trop juste en hauteur
coupe le dessus de l'objet (constaté avec la boîte d'annotation du livre, 2,3 cm).

**App, relecture.** Corrigé dans le code, **non compilé** (dépôt privé, Actions bloqué) : rien ne maintenait
l'iPhone éveillé pendant un scan ; « Finition du modèle » pouvait rester affiché pour toujours si l'événement de
fin était manqué ; le X en pause supprimait le scan sans prévenir ; un résultat vide était annoncé « Modèle prêt » ;
un scan pouvait démarrer calculateur éteint ; tutoiements et messages techniques ; réglage de la teinte invisible
sans LiDAR ; vue 3D cadrée sur la boîte au lieu du plat. Relevé, non traité : l'écran du plat affiche la géométrie
à couleurs par sommet et non le fichier texturé ; pas de vue en réalité augmentée (USDZ).

80 tests passés, 1 sauté. Deux redémarrages du serveur par manque de mémoire pendant ces essais (calculs lourds
lancés en parallèle) ; les mesures ci-dessus viennent d'exécutions refaites une par une.

## Mise à jour du 20 novembre (suite) — boîte trop basse, aperçu en direct, réalité augmentée, modèle de profondeur en parallèle (moteur `p1-0.9.0`)

Les points laissés « constatés, non corrigés » ou « relevés, non traités » à la mise à jour précédente.

**1. Boîte de scan trop basse (`coordinates.headroom`).** La boîte est réglée à la main ; trop basse, elle rasait le
dessus du plat. Ce qui dépasse de la boîte, dans son contour, est maintenant gardé jusqu'à la moitié de sa hauteur,
au moins 2 cm, au plus 6 cm (recherche stéréo, découpe des mesures, fusion, maillage, fermeture), **à condition de
prolonger une surface qui part de l'intérieur de la boîte**. Les côtés et la base ne bougent pas : la table et les
voisins du plat y sont.

La condition vient d'une mesure, pas d'un principe. Première version : tout garder au-dessus de la boîte, « puisqu'il
n'y a que de l'air ». Sur le bol uni de synthèse (rien de réel au-dessus de la boîte), la stéréo y plaçait alors
jusqu'à 22 000 pixels par vue, **tous faux** (erreur de 50 à 60 % : la table du fond appariée trop près), que le
haut de la boîte éliminait jusque-là ; le comblement des surfaces unies tombait de 33 vues sur 34 à 14. Une tache
isolée au-dessus de la boîte est donc de nouveau rejetée (`stereo_depth.drop_floating_above`) ; avec la condition,
32 vues sur 34. Conséquence : ce qui dépasse sans tenir au reste du plat dans l'image (un décor au bout d'une pique)
n'est pas gardé, comme avant.

| Vérification | Avant | Après |
|---|---|---|
| Synthèse, boîte de 12 mm pour un plat de 34 mm : pixels du dessus de l'aliment mesurés (sur 1 309) | 75 | 1 030 |
| Vraie capture (tasse de 10,9 cm, boîte volontairement baissée à 7,5 cm), aperçu en direct : surface | 122 cm² | 191 cm², bord supérieur présent, modèle 34 mm au-dessus de la boîte |
| Vraie capture du livre avec sa boîte d'annotation de 2,3 cm, finition complète | livre entier | livre entier, identique |

La dernière ligne corrige ce qui était écrit plus haut : avec le moteur `p1-0.8.0` final le livre n'était déjà plus
coupé (la coupe venait d'un état intermédiaire du recalage). Le gain est donc montré sur la tasse, pas sur le
livre. Image : `docs/evidence/boite_trop_basse_avant_apres.jpg`. Au-delà de la marge le modèle est coupé net : le
verdict porte alors `box_too_low`, ne peut plus être « bon », et l'app demande de monter la boîte (texte ajouté,
non compilé). L'en-tête de chaque aperçu donne `above_box_mm`.

**2. Aperçu pendant le scan (`live_pose.py`).** Diagnostic d'abord : sur les chaussures, en direct, 41,4 % des
mesures contredites avec les positions du suivi, 11,1 % avec les positions recalées de la finition ; le contrôle de
couleur n'en explique que 4 points. La cause est la position des vues : à 4 cm d'écart entre deux photos, 1 mm
d'erreur du suivi fait 3 % de profondeur. Le recalage global a besoin de toutes les vues ; pendant le scan, chaque
nouvelle vue est donc attachée à celles déjà traitées, avant le calcul de sa profondeur :
- les points du plat retrouvés dans une vue déjà fusionnée ont une profondeur confirmée (gardée pour tout le scan,
  quelques kilo-octets par vue) : ils doivent se projeter là où la nouvelle vue les voit — c'est ce qui fixe la
  distance entre caméras, que les images seules ne voient pas ;
- les autres correspondances (table, décor) doivent rester sur leur droite épipolaire : orientation et direction ;
- 80 % de la correction est appliquée ; une solution à plus de 15 mm ou 1,5° du suivi est refusée ; une vue
  impossible à attacher est placée d'après la correction commune de ses voisines plutôt que laissée à sa position
  brute ; une vue qui concorde déjà (0,8 px) n'est pas touchée.

Aperçu en direct, vraies captures, même code livré, attache désactivée → activée :

| Capture | Mesures confirmées | Contredites | Vues attachées | Temps de calcul par vue (4 cœurs) |
|---|---|---|---|---|
| Chaussures, 85 vues | 51,1 → 84,9 % | 41,4 → 10,4 % | 74, 2 placées d'après les voisines, 8 déjà justes | 526 → 700 ms |
| Livre, 94 vues | 31,3 → 56,3 % | 43,6 → 22,5 % | 86, 4 d'après les voisines, 3 déjà justes | 555 → 674 ms |
| Boîtes imprimées A, 75 vues | 52,9 → 67,7 % | 36,9 → 23,4 % | 60, 5 d'après les voisines, 6 refusées | 394 → 528 ms |
| Boîtes imprimées B, 83 vues | 72,5 → 82,6 % | 20,1 → 11,4 % | 70, 9 déjà justes, 2 refusées | 532 → 640 ms |
| Tasse sombre, 82 vues | 78,0 → 81,1 % | 15,0 → 12,7 % | 38, 10 refusées (trop peu de points connus) | 427 → 452 ms |
| Tasse unie, 89 vues | 60,1 % | 28,7 % | 0 : pas assez de points connus, rien ne change | 348 → 381 ms |

Positions comparées à celles de la finition (écart entre vues voisines, médiane) : chaussures 1,00 → 0,57 mm, livre
1,12 → 0,51 mm. Scène de synthèse à suivi bruité (1,5 mm / 0,15° par vue) : confirmées 35,2 → 92,8 %, contredites
55,0 → 5,2 %, erreur du modèle au 80ᵉ centile 9,2 → 5,7 mm ; suivi exact : 0 à 3 vues touchées sur 60. Image :
`docs/evidence/apercu_direct_avant_apres.jpg`.

Variantes mesurées sur trois captures (chaussures / livre / boîtes A, mesures contredites) et écartées — chiffres
pris juste avant le rejet des taches flottantes du point 1, qui les déplace d'un ou deux points :

| Réglage | Chaussures | Livre | Boîtes A | Ce qui se passe |
|---|---|---|---|---|
| Retenu : 80 %, refus au-delà de 15 mm du suivi | 10,4 % | 22,5 % | 23,4 % | — |
| 100 % de la correction | 16,5 % | 29,5 % | 11,9 % | surfaces plus lisses, mais le modèle s'écarte du suivi (taille +2 à +3 %) puis les vues sont refusées en série |
| 100 % + retour lent de l'écart commun aux voisines | 9,4 % | 31,8 % | 13,2 % | le livre décroche au second passage |
| Profondeur calculée avec la position exacte, posée avec la position ramenée | 29,9 % | 32,1 % | 18,4 % | le modèle devient incohérent avec lui-même |
| 90 ou 100 %, écart jugé par rapport aux voisines et non au suivi | 6,6 / 19,6 % | 26,3 / 17,3 % | 27,1 / 30,9 % | dérive jusqu'à 25 à 58 mm du suivi |

**Limites constatées.** Le modèle en direct peut être plus grand que le vrai de 0,6 à 1,7 % et décalé de quelques
millimètres (il hérite de l'échelle des premières vues) : sans conséquence sur le résultat final, que la finition
recalcule entièrement à partir du suivi. Sans repères visuels sur l'objet (tasse unie), rien n'est attaché. Le
livre garde 22 % de mesures contredites. Le bon réglage dépend encore de la capture (boîtes A : 12 % atteignables,
23 % obtenus) ; corriger proprement demanderait de fixer l'échelle du modèle dès le départ.

**Trouvé en chemin.** `cv2.recoverPose` (choix entre les quatre décompositions de la matrice essentielle) prenait
170 à 280 ms par paire, plus que l'appariement stéréo. Remplacé par un calcul direct (`stereo_depth.recover_pose`) :
même rotation et même direction sur 40 tirages, masques différents d'au plus 15 points sur environ 1 500, moins
d'1 ms. Temps par vue sans attache : 659 → 509 ms sur les chaussures, à machine au repos (les temps du tableau
ci-dessus sont pris après ce gain, dans une même série) ; au total une vue coûte à peu près ce qu'elle coûtait avant
cette mise à jour. La finition en profite aussi.

**3. Modèle texturé pour la réalité augmentée (`exports.write_usdz`).** La finition écrit `model.usdz` à côté de
`model.glb` : même maillage, même texture, pour l'ouverture par iOS (vue 3D et pose sur la table), sans dépendance
ajoutée. C'est une archive zip non compressée, fichiers alignés sur 64 octets, dont le premier est la scène en
texte (USDA), comme le fait three.js pour `<model-viewer>`.
- Vérifié ici : structure de l'archive (non compressée, alignée, sommes de contrôle), unités et axe, relecture des
  points, triangles, normales ; coordonnées de texture retournées (glTF compte du haut, USD du bas) ; image
  identique à celle du GLB ; test de bout en bout sur la finition d'une scène de synthèse.
- Vérifié aussi dans un navigateur de test avec le lecteur USDZ de three.js (un lecteur indépendant, pas celui
  d'Apple), sur deux vraies captures (chaussures et livre, 60 000 triangles, 4,7 et 4,9 Mo) : un maillage, la bonne
  taille en mètres, la texture à l'endroit (le titre du livre se lit). Ce lecteur n'accepte que les textures PNG :
  l'essai porte sur la variante PNG du même fichier ; la variante JPEG livrée n'est contrôlée que par les tests de
  structure. Image : `docs/evidence/usdz_lu_par_threejs.jpg`.
- **Non vérifié** : l'ouverture dans AR Quick Look sur un iPhone ; le contrôle par la bibliothèque de Pixar (son
  installation a été refusée dans cet environnement ; le test existe et s'exécute dès qu'elle est présente).
- App (écrit, **non compilé**) : `model.usdz` est téléchargé avec les autres résultats ; l'écran du plat a un bouton
  « Voir sur votre table » qui l'ouvre avec l'aperçu d'iOS.

**4. Modèle de profondeur en parallèle (`mono_depth.AsyncMono`).** Le modèle tourne sur son propre fil, en avance
sur le moteur et en même temps que la stéréo ; il reçoit la moitié des cœurs. À la finition, le moteur attend
chaque prédiction. Pendant le scan, rien n'attend : une prédiction pas prête à 0,12 s près n'est pas utilisée (la
vue garde ce que la stéréo a mesuré), au plus trois demandes patientent (les plus anciennes sont abandonnées), et
si moins de 30 % des réponses arrivent à temps sur 12 vues le modèle se retire jusqu'à la finition. Il est
désormais actif pendant le scan par défaut (`DISHPLAY_MONO_LIVE=0` pour le réserver à la finition).
- Vérifié ici avec des modèles factices lents ou rapides (7 tests) et avec la prédiction simulée dans le moteur
  (les parois du bol sont comblées aussi bien qu'en appel direct).
- **Toujours non vérifié** : le vrai réseau n'a jamais été exécuté dans cet environnement ; sa vitesse et sa qualité
  sur votre PC restent à mesurer (`report.json` → `mono_fill.parallel` : demandées, à temps, en retard, abandonnées).

112 tests passés, 2 sautés (le vrai réseau de profondeur et la bibliothèque de Pixar, absents de cet environnement),
suite complète exécutée seule sur le code livré (12 min 52 s). App iOS : modifications **non compilées** (dépôt
privé, minutes Actions épuisées).

## Mise à jour du 20 novembre (soir) — nouvelle identité de l'app, modèle sans trous (moteur `p1-0.10.0`)

**App : refonte visuelle (écrite, non compilée).** Demande : une app « premium », d'autres couleurs, « un vrai
truc », le rendu des applications de 2026. Choix faits, tous modifiables en un endroit :
- **Identité du site** : papier crème, encre, et le bleu de « dishplay. » comme unique couleur d'action. L'orange
  en dégradé, les halos et le fond violet disparaissent.
- **Clair et sombre** : l'app suit le réglage de l'iPhone (elle était forcée en sombre). Le scan, posé sur l'image
  de la caméra, reste sombre ; les modèles 3D restent sur une « scène » sombre dans les deux cas.
- **Vrai verre d'iOS 26** (`glassEffect`, conteneur de verre, barre d'onglets système qui se replie au défilement),
  réservé à ce qui flotte : commandes au-dessus de la caméra, barres. Les cartes, qui sont du contenu, n'en ont
  pas. Avant iOS 26, le flou système.
- **Un système de design** (`ios/App/DesignSystem/`, un composant par fichier) : couleurs nommées par rôle dans le
  catalogue de l'app avec leurs deux valeurs (`tools/ios_colors.py` les écrit depuis une seule table), échelles
  d'espacement et de rayons, styles de texte bâtis sur ceux du système (ils suivent la taille de texte choisie par
  l'utilisateur), bouton principal, bouton discret, carte, scène, marque. Changer la couleur d'action tient en une
  ligne de la table.
- Écrans repris : accueil (marque, titre en deux tons, plat animé sur sa scène, un seul bouton coloré), Mes plats,
  fiche d'un plat, réglages, introduction, scan (jetons de couleur, verre groupé).
- Deux défauts d'usage corrigés en passant : toucher un plat sur l'accueil ouvre ce plat (et non la liste), avec
  l'état de son calcul ; abandonner un scan interrompu demande confirmation.

Maquette des cinq écrans, en clair et en sombre, avec trois couleurs d'action à essayer (bleu, tomate, encre) :
https://claude.ai/artifact/To3msLfaCC8kfxsDCg39gF (lien privé). C'est un dessin fait d'après le code, pas une
capture de l'app.

Vérifié ici, faute de compilateur Swift : chaque couleur nommée dans le code existe dans le catalogue
(`tools/ios_colors.py --check` : 13 utilisées, 0 manquante) ; plus aucun blanc ou noir écrit en dur hors de
l'écran de scan (ils seraient illisibles en clair) ; contrastes calculés sur la palette : au moins 4,75 pour 1
entre chaque texte et son fond, en clair comme en sombre (une paire était à 4,41, corrigée) ; accolades et
parenthèses équilibrées dans les fichiers réécrits ; le code suit les règles SwiftUI du projet (`swiftui-pro`,
`liquid-glass`, `design-system`, `typography`). **Non vérifié** : la compilation, le rendu réel sur iPhone en
clair et en sombre, les grandes tailles de texte, VoiceOver. Les revues `ui-review` et `accessibility-audit` restent à faire sur une
version compilée, avant publication.

**Modèle : les trous dans la surface (`closure.py`).** Les taches sombres visibles sur la couverture du livre
n'étaient pas un défaut de texture : c'étaient des trous de plus de 8 mm — des aplats unis, photographiés mais que
la stéréo n'a pas pu mesurer — par lesquels on voyait la base ajoutée sous l'objet. La règle des 8 mm (ne rien
poser à plus de 8 mm d'une mesure) les laissait ouverts. Désormais un trou plus large est fermé quand il est
entouré par la surface reconstruite, large de 6 cm au plus, et qu'au moins 35 % de sa surface a été vue par deux
caméras sans rien entre elles. L'extérieur du modèle, son dos et son dessous ne remplissent jamais ces conditions :
la « peau gonflée » de la première version ne revient pas. Tout ce qui est ajouté reste étiqueté « estimé », le
modèle tel que mesuré reste dans `model_mesure.glb`, et les photos sont ensuite projetées sur ces surfaces comme
sur le reste.

Deux défauts trouvés en chemin et corrigés : des trous d'épingle (quelques millimètres) restaient ouverts parce
que « hors de la surface » était jugé par une distance — un trou de 3 mm n'est jamais à plus d'1 mm de son bord ;
c'est maintenant jugé par ce qui recouvre ou non l'endroit. Et, après simplification, deux triangles pouvaient se
retrouver sur les trois mêmes sommets : l'atlas de texture refusait alors tout le maillage et le modèle serait
parti avec ses couleurs par sommet au lieu de ses photos.

Avant → après sur quatre vraies captures (même maillage mesuré, mêmes positions, mêmes photos ; seule la fin du
traitement change). Mesure : part de l'image, à l'intérieur du contour de l'objet, où le regard traverse le modèle.

| Capture | Vu de dessus | Vues obliques | Trous fermés | Restés ouverts |
|---|---|---|---|---|
| Livre | 4,0 → 0,06 % | 4,1 → 0,27 % | 5 (le plus large : 3,0 cm) | 2 au bord de la boîte, 1 jamais vu |
| Chaussures | 5,7 → 2,5 % | 15,0 → 13,0 % | 1 (5,5 cm, l'ouverture d'une chaussure) | 2 trop larges, 3 jamais vus |
| Tasse sombre | 24,8 → 24,5 % | 26,8 → 27,0 % | 1 (2,9 cm) | 1 trop large, 8 au bord de la boîte, 1 jamais vu |
| Boîtes imprimées A | 11,6 → 11,1 % | 33,6 → 33,4 % | 1 (1,7 cm) | 1 trop large, 16 au bord de la boîte, 2 jamais vus |

Le gain est net là où des aplats manquaient au milieu d'une surface (le livre : le titre se lit en entier), partiel
sur les chaussures, nul sur la tasse et les boîtes, dont les manques sont de grands pans jamais reconstruits et non
des trous. Fichier livré inchangé (2,7 à 2,9 Mo), fermeture en 2 à 4 s, texture et `model.usdz` produits sur les
quatre captures. Image : `docs/evidence/trous_fermes_avant_apres.jpg` (rendu dans le navigateur).

**Limites.** L'ouverture d'un vrai creux (une chaussure) est fermée par une surface dont la forme est estimée. Un
trou au bord de la boîte de scan reste ouvert. Les surfaces unies ou brillantes de grande étendue restent le rôle
du modèle de profondeur, toujours jamais exécuté ici.

119 tests passés, 2 sautés (le vrai réseau de profondeur et la bibliothèque de Pixar, absents ici), suite complète
exécutée seule sur le code livré (15 min 32 s). App iOS : toujours **non compilée** (dépôt privé).

## Ce qui reste à prouver sur appareil (vos essais, `FIRST_TEST.md`)
Suivi AR et boîte sur l'iPhone 13, autorisation Réseau local, cadence et chauffe, latence Wi‑Fi réelle (images de
~0,5 Mo), qualité sur aliments brillants/unis, reprise après coupure, épinglage TLS sur iOS, rendu Metal, export.
