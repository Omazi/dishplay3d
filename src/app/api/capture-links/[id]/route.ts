import { NextResponse } from 'next/server';
import { api } from '@/lib/server/http';
import { requireUser } from '@/lib/server/auth';
import { database } from '@/lib/server/db';
import { ApiError, idField } from '@/lib/server/domain';
import { audit, lockRestaurant } from '@/lib/server/catalogue';
export const DELETE = api(async (request, context: { params: Promise<{ id: string }> }) => {
  const identity = await requireUser(request);
  const id = idField((await context.params).id);
  await (
    await database()
  ).transaction(async (tx) => {
    await lockRestaurant(tx, identity.restaurantId);
    const { rows } = await tx.query(
      'UPDATE native_capture_links SET revoked_at=COALESCE(revoked_at,now()) WHERE id=$1 AND restaurant_id=$2 RETURNING id',
      [id, identity.restaurantId],
    );
    if (!rows[0]) throw new ApiError(404, 'Association not found.', 'NOT_FOUND');
    await audit(tx, identity.restaurantId, identity.user.id, 'capture.link.revoked', {
      linkId: id,
    });
  });
  return NextResponse.json({ revoked: true });
});
