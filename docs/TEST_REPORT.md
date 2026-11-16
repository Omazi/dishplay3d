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
| Distribué TestFlight | **non** : IPA signée produite (run 43795707664) mais envoi refusé par Apple — contrat Apple à renouveler par le titulaire du compte (`TESTFLIGHT.md`) |
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

## Ce qui reste à prouver sur appareil (vos essais, `FIRST_TEST.md`)
Suivi AR et boîte sur l'iPhone 13, autorisation Réseau local, cadence et chauffe, latence Wi‑Fi réelle (images de
~0,5 Mo), qualité sur aliments brillants/unis, reprise après coupure, épinglage TLS sur iOS, rendu Metal, export.
