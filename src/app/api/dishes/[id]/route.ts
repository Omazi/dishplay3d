import { NextResponse } from 'next/server';
import { api, jsonBody } from '@/lib/server/http';
import { newId, requireUser } from '@/lib/server/auth';
import { database } from '@/lib/server/db';
import { ApiError, idField } from '@/lib/server/domain';
import {
  audit,
  bumpRestaurant,
  dishFromRow,
  expectVersion,
  lockRestaurant,
  validatedDish,
} from '@/lib/server/catalogue';

type Context = { params: Promise<{ id: string }> };
export const PATCH = api(async (request, context: Context) => {
  const identity = await requireUser(request);
  const id = idField((await context.params).id);
  const body = await jsonBody(request);
  const dish = await (
    await database()
  ).transaction(async (tx) => {
    await lockRestaurant(tx, identity.restaurantId);
    const previous = (
      await tx.query('SELECT * FROM dishes WHERE id=$1 AND restaurant_id=$2', [
        id,
        identity.restaurantId,
      ])
    ).rows[0];
    if (!previous) throw new ApiError(404, 'Dish not found.', 'NOT_FOUND');
    expectVersion(previous.version, body.version);
    const old = dishFromRow(previous);
    const d = await validatedDish(tx, identity.restaurantId, body, old);
    const changedModel = old.modelGlbUrl !== d.modelGlbUrl || old.modelUsdzUrl !== d.modelUsdzUrl;
    if (changedModel && old.modelGlbUrl)
      await tx.query(
        'INSERT INTO dish_revisions(id,dish_id,restaurant_id,geometry_revision,model_glb_url,model_usdz_url,source) VALUES($1,$2,$3,$4,$5,$6,$7)',
        [
          newId(),
          id,
          identity.restaurantId,
          old.version,
          old.modelGlbUrl,
          old.modelUsdzUrl,
          previous.model_source || 'owner-imported',
        ],
      );
    const { rows } = await tx.query(
      `UPDATE dishes SET category_id=$1,name=$2,description=$3,price_cents=$4,allergens=$5,image_id=$6,model_glb_url=$7,model_usdz_url=$8,sort_order=$9,is_available=$10,version=version+1,model_source=$11 WHERE id=$12 AND restaurant_id=$13 RETURNING *`,
      [
        d.categoryId,
        d.name,
        d.description,
        d.priceCents,
        JSON.stringify(d.allergens),
        d.imageId,
        d.modelGlbUrl,
        d.modelUsdzUrl,
        d.sortOrder,
        d.isAvailable,
        d.modelGlbUrl ? (changedModel ? 'owner-imported' : previous.model_source) : null,
        id,
        identity.restaurantId,
      ],
    );
    await bumpRestaurant(tx, identity.restaurantId);
    await audit(tx, identity.restaurantId, identity.user.id, 'dish.updated', {
      dishId: id,
      changedModel,
    });
    return dishFromRow(rows[0]);
  });
  return NextResponse.json({ dish });
});
export const DELETE = api(async (request, context: Context) => {
  const identity = await requireUser(request);
  const id = idField((await context.params).id);
  const body = await jsonBody(request);
  await (
    await database()
  ).transaction(async (tx) => {
    await lockRestaurant(tx, identity.restaurantId);
    const previous = (
      await tx.query('SELECT version FROM dishes WHERE id=$1 AND restaurant_id=$2', [
        id,
        identity.restaurantId,
      ])
    ).rows[0];
    if (!previous) throw new ApiError(404, 'Dish not found.', 'NOT_FOUND');
    expectVersion(previous.version, body.version);
    if (
      (
        await tx.query(
          'SELECT id FROM scan_sessions WHERE dish_id=$1 AND restaurant_id=$2 LIMIT 1',
          [id, identity.restaurantId],
        )
      ).rows[0]
    )
      throw new ApiError(
        409,
        'This dish has saved captures. Mark it unavailable to preserve its original photos and capture history.',
        'HAS_SAVED_CAPTURES',
      );
    await tx.query('DELETE FROM dishes WHERE id=$1 AND restaurant_id=$2', [
      id,
      identity.restaurantId,
    ]);
    await bumpRestaurant(tx, identity.restaurantId);
    await audit(tx, identity.restaurantId, identity.user.id, 'dish.deleted', { dishId: id });
  });
  return NextResponse.json({ ok: true });
});
