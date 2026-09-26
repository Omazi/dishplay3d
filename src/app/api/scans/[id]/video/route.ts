import { api } from '@/lib/server/http';
import { requireUser } from '@/lib/server/auth';
import { database } from '@/lib/server/db';
import { idField } from '@/lib/server/domain';
import { ownedScan } from '@/lib/server/scans';
import { lockRestaurant } from '@/lib/server/catalogue';
import { receiveVideo, attachVideo } from '@/lib/server/capture-video';

export const runtime = 'nodejs';
export const POST = api(async (request, context: { params: Promise<{ id: string }> }) => {
  const identity = await requireUser(request);
  const id = idField((await context.params).id);
  const db = await database();
  await ownedScan(db, id, identity.restaurantId);
  const { store, blob, mime } = await receiveVideo(request);
  let attached = false;
  try {
    const result = await db.transaction(async (tx) => {
      await lockRestaurant(tx, identity.restaurantId);
      return attachVideo(tx, id, identity.restaurantId, blob, mime);
    });
    attached = !result.duplicate;
    return Response.json(
      { ...result, sha256: blob.sha256, bytes: blob.bytes, validation: 'pending_worker_decode' },
      { status: result.duplicate ? 200 : 201 },
    );
  } finally {
    if (!attached) await store.discard(blob.key);
  }
});
