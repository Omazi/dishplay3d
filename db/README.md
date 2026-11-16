# Base de données et stockage des fichiers

Aucune base n'est branchée pour l'instant : ce dossier contient le **modèle** (du SQL PostgreSQL), vérifié sur une
vraie base PostgreSQL embarquée.

## Où est quoi

- Le site web (branche `main1`) a déjà ses migrations `001` à `005` : comptes, restaurants, catégories, plats,
  menus publiés, un lien QR par restaurant, scans, file de reconstruction.
- `db/migrations/006_storage_and_3d_assets.sql` s'ajoute par-dessus, sans rien casser (ré-exécutable).

## Ce que le modèle garantit

| Besoin | Tables |
|---|---|
| Chaque restaurant a ses propres plats et catégories | `restaurants`, `categories`, `dishes` (site) |
| Chaque restaurant a sa propre adresse | `restaurants.slug` → `/menu/{slug}` ; `restaurant_domains` pour un nom de domaine à lui |
| Chaque restaurant a sa propre apparence | `restaurant_themes` (couleurs, police, logo, image de couverture) |
| Chaque restaurant a ses codes QR | `qr_codes` : autant que voulu (un par table, terrasse, vitrine), vers le menu, une catégorie ou un plat. L'adresse imprimée `/q/{code}` reste valable si le menu change |
| Les fichiers ne sont pas dans la base | `storage_objects` : une ligne par fichier (compartiment, chemin, type, taille, empreinte) |
| Modèles 3D d'un plat | `dish_models` : un résultat par scan (GLB, USDZ, splat, image, vidéo), historique gardé, **un seul publié par plat** |
| Menu en plusieurs langues | `dish_translations`, `category_translations` |
| Savoir ce que les clients regardent | `menu_events` (sans adresse IP ni compte) |

**Cloisonnement entre restaurants, imposé par la base elle-même** : une ligne d'un restaurant ne peut pointer que
vers des plats et des fichiers du même restaurant (clés étrangères doubles `(id, restaurant_id)`), et le chemin d'un
fichier doit commencer par `r/{id du restaurant}/`. Supprimer un restaurant supprime tout ce qui lui appartient.

## Stockage des fichiers (S3 ou compatible)

La base ne contient que l'adresse des fichiers. N'importe quel service compatible S3 convient (Amazon S3,
Cloudflare R2, etc.) ; le choix du fournisseur n'est pas fait et le modèle n'en dépend pas.

```
r/{restaurant}/brand/logo.png, cover.jpg
r/{restaurant}/dishes/{plat}/images/{empreinte}.jpg
r/{restaurant}/dishes/{plat}/models/{modèle}/model.glb, model.usdz, splat.ply, poster.jpg, turntable.mp4
r/{restaurant}/scans/{scan}/frames/000001.jpg + .json        (vues brutes, privées)
r/{restaurant}/qr/{qr}.png
```

- Les fichiers ne changent jamais une fois écrits (un nouveau modèle = un nouveau dossier), ce qui permet de les
  mettre en cache longtemps.
- Privé par défaut ; seuls les fichiers d'un modèle publié sont servis au public (`visibility = 'public'`).
- Envoi direct depuis l'iPhone ou le calculateur avec une adresse signée à durée courte, délivrée par le serveur :
  les clés du stockage ne quittent jamais le serveur.
- À décider plus tard : durée de conservation des vues brutes d'un scan (elles pèsent le plus lourd).

## Vérifier le modèle

```
npm install @electric-sql/pglite
node db/check_schema.mjs <dossier migrations du site>
```

Le script applique 001 à 006 (deux fois pour 006), puis tente 22 opérations : celles qui doivent passer passent,
et celles qui violeraient le cloisonnement (fichier d'un autre restaurant, QR vers le plat d'un autre, deuxième
modèle publié, photo sans contenu…) sont refusées. Résultat au 16 novembre 2026 : tout passe.

## Limites

- Pas encore relié au code du site ni à l'app : c'est le modèle seul.
- Les photos déjà enregistrées dans la base (`media_assets.content_base64`) y restent ; les déplacer vers le
  stockage est une étape à part.
- Pas de sécurité au niveau des lignes (RLS) : le cloisonnement repose sur les contraintes ci-dessus et sur le code
  du serveur. À ajouter si plusieurs services accèdent directement à la base.
