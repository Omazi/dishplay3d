import { NextResponse } from 'next/server';
import { api, jsonBody } from '@/lib/server/http';
import { requireUser } from '@/lib/server/auth';
import { database } from '@/lib/server/db';
import { ApiError, idField, integerField, textField } from '@/lib/server/domain';
import { bumpRestaurant, lockRestaurant } from '@/lib/server/catalogue';

type Context = { params: Promise<{ id: string }> };
export const PATCH = api(async (request, context: Context) => {
  const identity = await requireUser(request);
  const id = idField((await context.params).id);
  const body = await jsonBody(request);
  const category = await (
    await database()
  ).transaction(async (tx) => {
    await lockRestaurant(tx, identity.restaurantId);
    const previous = (
      await tx.query('SELECT * FROM categories WHERE id=$1 AND restaurant_id=$2', [
        id,
        identity.restaurantId,
      ])
    ).rows[0];
    if (!previous) throw new ApiError(404, 'Category not found.', 'NOT_FOUND');
    const name = textField(body.name ?? previous.name, 'Category name', 100, true);
    const sortOrder = integerField(body.sortOrder ?? previous.sort_order, 'Sort order', 100_000);
    await tx.query('UPDATE categories SET name=$1,sort_order=$2 WHERE id=$3 AND restaurant_id=$4', [
      name,
      sortOrder,
      id,
      identity.restaurantId,
    ]);
    await bumpRestaurant(tx, identity.restaurantId);
    return { id, name, sortOrder };
  });
  return NextResponse.json({ category });
});
export const DELETE = api(async (request, context: Context) => {
  const identity = await requireUser(request);
  const id = idField((await context.params).id);
  await (
    await database()
  ).transaction(async (tx) => {
    await lockRestaurant(tx, identity.restaurantId);
    await tx.query(
      'UPDATE dishes SET category_id=NULL,version=version+1 WHERE category_id=$1 AND restaurant_id=$2',
      [id, identity.restaurantId],
    );
    const { rows } = await tx.query(
      'DELETE FROM categories WHERE id=$1 AND restaurant_id=$2 RETURNING id',
      [id, identity.restaurantId],
    );
    if (!rows[0]) throw new ApiError(404, 'Category not found.', 'NOT_FOUND');
    await bumpRestaurant(tx, identity.restaurantId);
  });
  return NextResponse.json({ ok: true });
});
