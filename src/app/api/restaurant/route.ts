import { NextResponse } from 'next/server';
import { api, jsonBody } from '@/lib/server/http';
import { requireUser } from '@/lib/server/auth';
import { database } from '@/lib/server/db';
import { ApiError, textField } from '@/lib/server/domain';
import {
  audit,
  expectVersion,
  lockRestaurant,
  restaurantFromRow,
  workspace,
} from '@/lib/server/catalogue';

export const GET = api(async (request) => {
  const identity = await requireUser(request);
  const db = await database();
  return NextResponse.json(
    await db.transaction(async (tx) => {
      await lockRestaurant(tx, identity.restaurantId);
      return workspace(tx, identity.restaurantId);
    }),
  );
});
export const PATCH = api(async (request) => {
  const identity = await requireUser(request);
  const body = await jsonBody(request);
  const result = await (
    await database()
  ).transaction(async (tx) => {
    const previous = await lockRestaurant(tx, identity.restaurantId);
    expectVersion(previous.version, body.version);
    const name = textField(body.name ?? previous.name, 'Restaurant name', 120, true);
    const tagline = textField(body.tagline ?? previous.tagline, 'Tagline', 240);
    const currency = textField(
      body.currency ?? previous.currency,
      'Currency',
      3,
      true,
    ).toUpperCase();
    if (!['EUR', 'USD', 'CAD'].includes(currency))
      throw new ApiError(400, 'Choose EUR, USD or CAD.');
    const { rows } = await tx.query(
      'UPDATE restaurants SET name=$1,tagline=$2,currency=$3,version=version+1 WHERE id=$4 RETURNING *',
      [name, tagline, currency, identity.restaurantId],
    );
    await audit(tx, identity.restaurantId, identity.user.id, 'restaurant.updated');
    return restaurantFromRow(rows[0]);
  });
  return NextResponse.json({ restaurant: result });
});
