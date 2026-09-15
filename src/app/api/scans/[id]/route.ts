import { NextResponse } from 'next/server';
import { api } from '@/lib/server/http';
import { requireUser } from '@/lib/server/auth';
import { database } from '@/lib/server/db';
import { ApiError, idField } from '@/lib/server/domain';
import { lockRestaurant } from '@/lib/server/catalogue';
import { ownedScan, scanFrames, scanFromRow } from '@/lib/server/scans';

type Context = { params: Promise<{ id: string }> };
export const GET = api(async (request, context: Context) => {
  const identity = await requireUser(request);
  const id = idField((await context.params).id);
  const data = await (
    await database()
  ).transaction(async (tx) => {
    const row = await ownedScan(tx, id, identity.restaurantId, true);
    const frames = await scanFrames(tx, id);
    return { scan: { ...scanFromRow(row), frameCount: frames.length }, frames };
  });
  return NextResponse.json(data, {
    headers: request.nextUrl.searchParams.has('download')
      ? { 'Content-Disposition': `attachment; filename="dishplay-capture-${id}.json"` }
      : {},
  });
});
export const DELETE = api(async (request, context: Context) => {
  const identity = await requireUser(request);
  const id = idField((await context.params).id);
  await (
    await database()
  ).transaction(async (tx) => {
    await lockRestaurant(tx, identity.restaurantId);
    const scan = await ownedScan(tx, id, identity.restaurantId, true);
    if (scan.state === 'finalized')
      throw new ApiError(
        409,
        'Finalized capture inputs are immutable. Your originals remain available.',
        'SCAN_FINALIZED',
      );
    await tx.query("UPDATE scan_sessions SET state='cancelled' WHERE id=$1", [id]);
  });
  return NextResponse.json({ ok: true, originalsPreserved: true });
});
