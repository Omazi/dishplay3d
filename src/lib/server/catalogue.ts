import type { Category, Dish, PublicMenu, Restaurant } from '@/lib/contracts';
import { demoMenu } from '@/lib/demo';
import { database, type Queryable, type Row } from './db';
import {
  allergensField,
  ApiError,
  idField,
  integerField,
  modelUrl,
  textField,
  versionField,
} from './domain';
import { newId } from './auth';

export function restaurantFromRow(row: Row): Restaurant {
  return {
    id: String(row.id),
    name: String(row.name),
    slug: String(row.slug),
    tagline: String(row.tagline),
    currency: String(row.currency),
    version: Number(row.version),
  };
}
export function dishFromRow(row: Row): Dish {
  return {
    id: String(row.id),
    categoryId: row.category_id === null ? null : String(row.category_id),
    name: String(row.name),
    description: String(row.description),
    priceCents: Number(row.price_cents),
    allergens: row.allergens as string[],
    imageId: row.image_id === null ? null : String(row.image_id),
    modelGlbUrl: row.model_glb_url === null ? null : String(row.model_glb_url),
    modelUsdzUrl: row.model_usdz_url === null ? null : String(row.model_usdz_url),
    version: Number(row.version),
    sortOrder: Number(row.sort_order),
    isAvailable: Boolean(row.is_available),
  };
}
export async function lockRestaurant(db: Queryable, restaurantId: string): Promise<Row> {
  const { rows } = await db.query('SELECT * FROM restaurants WHERE id=$1 FOR UPDATE', [
    restaurantId,
  ]);
  if (!rows[0]) throw new ApiError(404, 'Restaurant not found.', 'NOT_FOUND');
  return rows[0];
}
export async function bumpRestaurant(db: Queryable, restaurantId: string): Promise<void> {
  await db.query('UPDATE restaurants SET version=version+1 WHERE id=$1', [restaurantId]);
}
export async function workspace(db: Queryable, restaurantId: string): Promise<PublicMenu> {
  const { rows } = await db.query('SELECT * FROM restaurants WHERE id=$1', [restaurantId]);
  if (!rows[0]) throw new ApiError(404, 'Restaurant not found.', 'NOT_FOUND');
  const categories = await db.query(
    'SELECT * FROM categories WHERE restaurant_id=$1 ORDER BY sort_order,name,id',
    [restaurantId],
  );
  const dishes = await db.query(
    'SELECT * FROM dishes WHERE restaurant_id=$1 ORDER BY sort_order,name,id',
    [restaurantId],
  );
  return {
    restaurant: restaurantFromRow(rows[0]),
    categories: categories.rows.map((c): Category => ({
      id: String(c.id),
      name: String(c.name),
      sortOrder: Number(c.sort_order),
    })),
    dishes: dishes.rows.map(dishFromRow),
    publishedAt: rows[0].published_at ? new Date(String(rows[0].published_at)).toISOString() : null,
  };
}
export async function getPublishedMenu(slug: string): Promise<PublicMenu | null> {
  if (slug === 'demo') return demoMenu;
  if (!/^[a-z0-9-]{1,80}$/.test(slug)) return null;
  const db = await database();
  const { rows } = await db.query(
    `SELECT p.snapshot FROM published_menu_versions p JOIN restaurants r ON r.id=p.restaurant_id WHERE r.slug=$1 ORDER BY p.version DESC LIMIT 1`,
    [slug],
  );
  return rows[0] ? (rows[0].snapshot as unknown as PublicMenu) : null;
}
export async function audit(
  db: Queryable,
  restaurantId: string,
  actorId: string,
  action: string,
  details: Record<string, unknown> = {},
): Promise<void> {
  await db.query(
    'INSERT INTO audit_events(id,restaurant_id,actor_id,action,details) VALUES($1,$2,$3,$4,$5)',
    [newId(), restaurantId, actorId, action, JSON.stringify(details)],
  );
}
export async function validatedDish(
  db: Queryable,
  restaurantId: string,
  body: Record<string, unknown>,
  previous?: Dish,
): Promise<Omit<Dish, 'id' | 'version'>> {
  const field = (key: keyof Dish, fallback: unknown): unknown =>
    body[key] === undefined ? (previous?.[key] ?? fallback) : body[key];
  const categoryValue = field('categoryId', null);
  const categoryId =
    categoryValue === null || categoryValue === '' ? null : idField(categoryValue, 'Category');
  if (
    categoryId &&
    !(
      await db.query('SELECT id FROM categories WHERE id=$1 AND restaurant_id=$2', [
        categoryId,
        restaurantId,
      ])
    ).rows[0]
  )
    throw new ApiError(400, 'Choose a category from this restaurant.');
  const imageValue = field('imageId', null);
  const imageId = imageValue === null || imageValue === '' ? null : idField(imageValue, 'Image');
  if (
    imageId &&
    !(
      await db.query('SELECT id FROM media_assets WHERE id=$1 AND restaurant_id=$2', [
        imageId,
        restaurantId,
      ])
    ).rows[0]
  )
    throw new ApiError(400, 'Choose an image uploaded to this restaurant.');
  const available = field('isAvailable', true);
  if (typeof available !== 'boolean')
    throw new ApiError(400, 'Availability must be true or false.');
  // Validate model URLs only when changed. A later origin configuration change never erases an existing model.
  const glb =
    body.modelGlbUrl === undefined && previous
      ? previous.modelGlbUrl
      : modelUrl(field('modelGlbUrl', null), 'glb');
  const usdz =
    body.modelUsdzUrl === undefined && previous
      ? previous.modelUsdzUrl
      : modelUrl(field('modelUsdzUrl', null), 'usdz');
  if (usdz && !glb) throw new ApiError(400, 'Add a GLB model before its optional USDZ version.');
  return {
    categoryId,
    imageId,
    name: textField(field('name', ''), 'Dish name', 120, true),
    description: textField(field('description', ''), 'Description', 2000),
    priceCents: integerField(field('priceCents', 0), 'Price in cents'),
    allergens: allergensField(field('allergens', [])),
    modelGlbUrl: glb,
    modelUsdzUrl: usdz,
    sortOrder: integerField(field('sortOrder', 0), 'Sort order', 100_000),
    isAvailable: available,
  };
}
export function expectVersion(actual: unknown, supplied: unknown): void {
  if (Number(actual) !== versionField(supplied))
    throw new ApiError(
      409,
      'This content changed in another window. Reload before saving.',
      'VERSION_CONFLICT',
    );
}
