import { NextResponse } from 'next/server';
import { api } from '@/lib/server/http';
import { requireUser } from '@/lib/server/auth';
import { database } from '@/lib/server/db';
import { idField } from '@/lib/server/domain';
import { lockRestaurant } from '@/lib/server/catalogue';
import { requestScanReconstruction } from '@/lib/server/automatic-reconstruction';
import { finalizeScan } from '@/lib/server/scans';

export const POST = api(async (request, context: { params: Promise<{ id: string }> }) => {
  const identity = await requireUser(request);
  const id = idField((await context.params).id);
  const result = await (
    await database()
  ).transaction(async (tx) => {
    await lockRestaurant(tx, identity.restaurantId);
    const scan = await finalizeScan(tx, id, identity.restaurantId, identity.user.id);
    const reconstruction = await requestScanReconstruction(
      tx,
      identity.restaurantId,
      identity.user.id,
      id,
    );
    return { scan, reconstruction };
  });
  return NextResponse.json(result);
});
