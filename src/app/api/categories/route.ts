import { NextResponse } from 'next/server';
import { api, jsonBody } from '@/lib/server/http';
import { newId, requireUser } from '@/lib/server/auth';
import { database } from '@/lib/server/db';
import { integerField, textField } from '@/lib/server/domain';
import { bumpRestaurant, lockRestaurant } from '@/lib/server/catalogue';

export const POST = api(async (request) => {
  const identity = await requireUser(request);
  const body = await jsonBody(request);
  const name = textField(body.name, 'Category name', 100, true);
  const sortOrder = integerField(body.sortOrder ?? 0, 'Sort order', 100_000);
  const id = newId();
  await (
    await database()
  ).transaction(async (tx) => {
    await lockRestaurant(tx, identity.restaurantId);
    await tx.query('INSERT INTO categories(id,restaurant_id,name,sort_order) VALUES($1,$2,$3,$4)', [
      id,
      identity.restaurantId,
      name,
      sortOrder,
    ]);
    await bumpRestaurant(tx, identity.restaurantId);
  });
  return NextResponse.json({ category: { id, name, sortOrder } }, { status: 201 });
});
