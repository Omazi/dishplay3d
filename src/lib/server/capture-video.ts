import { Readable } from 'node:stream';
import { type Queryable } from './db';
import { newId } from './auth';
import { ownedScan } from './scans';
import { ApiError } from './domain';
import {
  captureBlobStore,
  MAX_VIDEO_BYTES,
  type CaptureBlob,
  type CaptureBlobStore,
} from './capture-blob-store';

export async function receiveVideo(
  request: Request,
): Promise<{ store: CaptureBlobStore; blob: CaptureBlob; mime: string }> {
  const mime = request.headers.get('content-type')?.split(';')[0] ?? '';
  if (!['video/mp4', 'video/quicktime'].includes(mime))
    throw new ApiError(415, 'Use video/mp4 or video/quicktime.', 'VIDEO_INVALID');
  if (!request.body) throw new ApiError(400, 'A video body is required.', 'VIDEO_INVALID');
  if (Number(request.headers.get('content-length')) > MAX_VIDEO_BYTES)
    throw new ApiError(413, 'Video exceeds 256 MiB.', 'VIDEO_TOO_LARGE');
  const store = captureBlobStore();
  const source = Readable.fromWeb(
    request.body as import('node:stream/web').ReadableStream<Uint8Array>,
  );
  return {
    store,
    blob: await store.put(source, request.headers.get('x-content-sha256') ?? ''),
    mime,
  };
}
export async function attachVideo(
  tx: Queryable,
  scanId: string,
  restaurantId: string,
  blob: CaptureBlob,
  mime: string,
) {
  const scan = await ownedScan(tx, scanId, restaurantId, true);
  if (scan.state !== 'capturing') throw new ApiError(409, 'Capture is closed.', 'SCAN_CLOSED');
  if ((await tx.query('SELECT id FROM scan_frames WHERE scan_id=$1 LIMIT 1', [scanId])).rows.length)
    throw new ApiError(409, 'This capture already contains frames.', 'MIXED_CAPTURE_SOURCES');
  const previous = (await tx.query('SELECT * FROM capture_videos WHERE scan_id=$1', [scanId]))
    .rows[0];
  if (previous) {
    if (
      previous.sha256 !== blob.sha256 ||
      Number(previous.byte_size) !== blob.bytes ||
      previous.mime_type !== mime
    )
      throw new ApiError(409, 'This capture already contains another video.', 'VIDEO_CONFLICT');
    return { id: String(previous.id), duplicate: true };
  }
  const id = newId();
  await tx.query(
    'INSERT INTO capture_videos(id,scan_id,restaurant_id,storage_backend,storage_key,sha256,byte_size,mime_type) VALUES($1,$2,$3,$4,$5,$6,$7,$8)',
    [id, scanId, restaurantId, blob.backend, blob.key, blob.sha256, blob.bytes, mime],
  );
  await tx.query("UPDATE scan_sessions SET source_type='video',manifest_schema=2 WHERE id=$1", [
    scanId,
  ]);
  return { id, duplicate: false };
}
