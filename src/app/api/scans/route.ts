import { NextResponse } from 'next/server';
import { api, jsonBody } from '@/lib/server/http';
import { newId, requireUser } from '@/lib/server/auth';
import { database } from '@/lib/server/db';
import { ApiError, idField } from '@/lib/server/domain';
import { audit, lockRestaurant } from '@/lib/server/catalogue';
import { scanFromRow } from '@/lib/server/scans';

export const GET = api(async (request) => {
  const identity = await requireUser(request);
  const dishId = request.nextUrl.searchParams.get('dishId');
  if (dishId) idField(dishId, 'Dish');
  const { rows } = await (
    await database()
  ).query(
    `SELECT s.*, (SELECT count(*) FROM scan_frames f WHERE f.scan_id=s.id) AS frame_count FROM scan_sessions s WHERE s.restaurant_id=$1 ${dishId ? 'AND s.dish_id=$2' : ''} ORDER BY s.created_at DESC LIMIT 100`,
    dishId ? [identity.restaurantId, dishId] : [identity.restaurantId],
  );
  return NextResponse.json({ scans: rows.map(scanFromRow) });
});
export const POST = api(async (request) => {
  const identity = await requireUser(request);
  const body = await jsonBody(request);
  const dishId = idField(body.dishId, 'Dish');
  const scan = await (
    await database()
  ).transaction(async (tx) => {
    await lockRestaurant(tx, identity.restaurantId);
    if (
      !(
        await tx.query('SELECT id FROM dishes WHERE id=$1 AND restaurant_id=$2', [
          dishId,
          identity.restaurantId,
        ])
      ).rows[0]
    )
      throw new ApiError(404, 'Dish not found.', 'NOT_FOUND');
    const active = (
      await tx.query(
        "SELECT count(*)::integer AS count FROM scan_sessions WHERE restaurant_id=$1 AND state='capturing'",
        [identity.restaurantId],
      )
    ).rows[0];
    if (Number(active.count) >= 10)
      throw new ApiError(400, 'Finish or cancel an existing capture before creating another.');
    const id = newId();
    const { rows } = await tx.query(
      'INSERT INTO scan_sessions(id,restaurant_id,dish_id) VALUES($1,$2,$3) RETURNING *',
      [id, identity.restaurantId, dishId],
    );
    await audit(tx, identity.restaurantId, identity.user.id, 'scan.created', {
      scanId: id,
      dishId,
    });
    return scanFromRow(rows[0]);
  });
  return NextResponse.json({ scan }, { status: 201 });
});
