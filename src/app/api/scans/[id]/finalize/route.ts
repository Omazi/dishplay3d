import { NextResponse } from 'next/server';
import { api } from '@/lib/server/http';
import { requireUser } from '@/lib/server/auth';
import { database } from '@/lib/server/db';
import { idField } from '@/lib/server/domain';
import { lockRestaurant } from '@/lib/server/catalogue';
import { finalizeScan } from '@/lib/server/scans';

export const POST = api(async (request, context: { params: Promise<{ id: string }> }) => {
  const identity = await requireUser(request);
  const id = idField((await context.params).id);
  const scan = await (
    await database()
  ).transaction(async (tx) => {
    await lockRestaurant(tx, identity.restaurantId);
    return finalizeScan(tx, id, identity.restaurantId, identity.user.id);
  });
  return NextResponse.json({ scan });
});
