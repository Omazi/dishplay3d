import { NextResponse } from 'next/server';
import { api, jsonBody } from '@/lib/server/http';
import { newId, requireUser } from '@/lib/server/auth';
import { database } from '@/lib/server/db';
import { ApiError } from '@/lib/server/domain';
import { audit, expectVersion, lockRestaurant, workspace } from '@/lib/server/catalogue';

export const POST = api(async (request) => {
  const identity = await requireUser(request);
  const body = await jsonBody(request);
  const result = await (
    await database()
  ).transaction(async (tx) => {
    const restaurant = await lockRestaurant(tx, identity.restaurantId);
    expectVersion(restaurant.version, body.version);
    const prior = (
      await tx.query(
        'SELECT created_at FROM published_menu_versions WHERE restaurant_id=$1 AND version=$2',
        [identity.restaurantId, restaurant.version],
      )
    ).rows[0];
    const publishedAt = prior
      ? new Date(String(prior.created_at)).toISOString()
      : new Date().toISOString();
    if (!prior) {
      const snapshot = await workspace(tx, identity.restaurantId);
      snapshot.publishedAt = publishedAt;
      snapshot.dishes = snapshot.dishes.filter((dish) => dish.isAvailable);
      if (!snapshot.dishes.length)
        throw new ApiError(400, 'Add at least one available dish before publishing.');
      await tx.query(
        'INSERT INTO published_menu_versions(id,restaurant_id,version,snapshot,created_at) VALUES($1,$2,$3,$4,$5)',
        [newId(), identity.restaurantId, restaurant.version, JSON.stringify(snapshot), publishedAt],
      );
      // Retained snapshots keep their immutable assets available to already-open menus.
      for (const imageId of new Set(
        snapshot.dishes.flatMap((dish) => (dish.imageId ? [dish.imageId] : [])),
      )) {
        await tx.query(
          'INSERT INTO published_media(restaurant_id,media_id) VALUES($1,$2) ON CONFLICT DO NOTHING',
          [identity.restaurantId, imageId],
        );
      }
      await tx.query('UPDATE restaurants SET published_at=$1 WHERE id=$2', [
        publishedAt,
        identity.restaurantId,
      ]);
      await audit(tx, identity.restaurantId, identity.user.id, 'menu.published', {
        version: restaurant.version,
      });
    }
    return {
      slug: String(restaurant.slug),
      url: `/menu/${restaurant.slug}`,
      publishedAt,
      version: Number(restaurant.version),
    };
  });
  return NextResponse.json(result);
});
