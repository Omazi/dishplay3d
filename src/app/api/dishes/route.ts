import { NextResponse } from 'next/server';
import { api, jsonBody } from '@/lib/server/http';
import { newId, requireUser } from '@/lib/server/auth';
import { database } from '@/lib/server/db';
import { ApiError } from '@/lib/server/domain';
import {
  audit,
  bumpRestaurant,
  dishFromRow,
  lockRestaurant,
  validatedDish,
} from '@/lib/server/catalogue';

export const GET = api(async (request) => {
  const identity = await requireUser(request);
  const { rows } = await (
    await database()
  ).query('SELECT * FROM dishes WHERE restaurant_id=$1 ORDER BY sort_order,name,id', [
    identity.restaurantId,
  ]);
  return NextResponse.json({ dishes: rows.map(dishFromRow) });
});
export const POST = api(async (request) => {
  const identity = await requireUser(request);
  const body = await jsonBody(request);
  const dish = await (
    await database()
  ).transaction(async (tx) => {
    await lockRestaurant(tx, identity.restaurantId);
    const count = (
      await tx.query('SELECT count(*)::integer AS count FROM dishes WHERE restaurant_id=$1', [
        identity.restaurantId,
      ])
    ).rows[0];
    if (Number(count.count) >= 500)
      throw new ApiError(400, 'This pilot supports up to 500 dishes per restaurant.');
    const d = await validatedDish(tx, identity.restaurantId, body);
    const id = newId();
    const { rows } = await tx.query(
      `INSERT INTO dishes(id,restaurant_id,category_id,name,description,price_cents,allergens,image_id,model_glb_url,model_usdz_url,sort_order,is_available,model_source)
      VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13) RETURNING *`,
      [
        id,
        identity.restaurantId,
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
        d.modelGlbUrl ? 'owner-imported' : null,
      ],
    );
    await bumpRestaurant(tx, identity.restaurantId);
    await audit(tx, identity.restaurantId, identity.user.id, 'dish.created', { dishId: id });
    return dishFromRow(rows[0]);
  });
  return NextResponse.json({ dish }, { status: 201 });
});
