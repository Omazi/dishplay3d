import { api } from '@/lib/server/http';
import { database } from '@/lib/server/db';
import { withNativeCapture } from '@/lib/server/native-capture';
import { receiveVideo, attachVideo } from '@/lib/server/capture-video';

export const runtime = 'nodejs';
export const POST = api(
  async (request) => {
    const db = await database();
    const auth = request.headers.get('authorization');
    await withNativeCapture(db, auth, async () => undefined);
    const { store, blob, mime } = await receiveVideo(request);
    let attached = false;
    try {
      const result = await withNativeCapture(db, auth, (tx, grant) =>
        attachVideo(tx, String(grant.scan_id), String(grant.restaurant_id), blob, mime),
      );
      attached = !result.duplicate;
      return Response.json(
        { ...result, sha256: blob.sha256, bytes: blob.bytes, validation: 'pending_worker_decode' },
        { status: result.duplicate ? 200 : 201 },
      );
    } finally {
      if (!attached) await store.discard(blob.key);
    }
  },
  { nativeCapability: true },
);
