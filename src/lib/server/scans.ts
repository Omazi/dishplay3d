import { type Queryable, type Row } from './db';
import { digest, newId } from './auth';
import { audit } from './catalogue';
import { saveMedia } from './media';
import { ApiError } from './domain';

export function scanFromRow(row: Row) {
  return {
    id: String(row.id),
    dishId: String(row.dish_id),
    state: String(row.state),
    frameCount: Number(row.frame_count || 0),
    createdAt: new Date(String(row.created_at)).toISOString(),
    manifestHash: row.manifest_hash ? String(row.manifest_hash) : null,
  };
}
export async function ownedScan(
  tx: Queryable,
  id: string,
  restaurantId: string,
  lock = false,
): Promise<Row> {
  const { rows } = await tx.query(
    `SELECT * FROM scan_sessions WHERE id=$1 AND restaurant_id=$2${lock ? ' FOR UPDATE' : ''}`,
    [id, restaurantId],
  );
  if (!rows[0]) throw new ApiError(404, 'Capture not found.', 'NOT_FOUND');
  return rows[0];
}
export async function scanFrames(tx: Queryable, scanId: string) {
  const { rows } = await tx.query(
    'SELECT * FROM scan_frames WHERE scan_id=$1 ORDER BY created_at,id',
    [scanId],
  );
  return rows.map((row) => ({
    id: String(row.id),
    mediaId: String(row.media_id),
    sha256: String(row.sha256),
    url: `/api/media/${row.media_id}`,
    metadata: row.metadata as Record<string, unknown>,
  }));
}

// Caller holds the restaurant lock; all upload paths share the same limits.
export async function appendScanFrame(
  tx: Queryable,
  id: string,
  restaurantId: string,
  bytes: Uint8Array,
  mime: string,
) {
  const sha256 = digest(bytes);
  const scan = await ownedScan(tx, id, restaurantId, true);
  if (scan.state !== 'capturing')
    throw new ApiError(
      409,
      'This capture is closed. Start another capture to add new photos.',
      'SCAN_CLOSED',
    );
  const duplicate = (
    await tx.query('SELECT id,media_id FROM scan_frames WHERE scan_id=$1 AND sha256=$2', [
      id,
      sha256,
    ])
  ).rows[0];
  if (duplicate)
    return {
      frame: {
        id: String(duplicate.id),
        mediaId: String(duplicate.media_id),
        sha256,
        url: `/api/media/${duplicate.media_id}`,
      },
      duplicate: true,
    };
  const count = (
    await tx.query('SELECT count(*)::integer AS count FROM scan_frames WHERE scan_id=$1', [id])
  ).rows[0];
  if (Number(count.count) >= 150) throw new ApiError(400, 'A capture supports up to 150 photos.');
  const asset = await saveMedia(tx, restaurantId, bytes, mime);
  const frameId = newId();
  await tx.query('INSERT INTO scan_frames(id,scan_id,media_id,sha256) VALUES($1,$2,$3,$4)', [
    frameId,
    id,
    asset.id,
    sha256,
  ]);
  return { frame: { id: frameId, mediaId: asset.id, sha256, url: asset.url }, duplicate: false };
}

export async function finalizeScan(
  tx: Queryable,
  id: string,
  restaurantId: string,
  actorId: string,
) {
  const previous = await ownedScan(tx, id, restaurantId, true);
  if (previous.state === 'cancelled')
    throw new ApiError(409, 'This capture was cancelled.', 'SCAN_CANCELLED');
  const frames = await scanFrames(tx, id);
  if (previous.state === 'finalized')
    return { ...scanFromRow(previous), frameCount: frames.length };
  if (frames.length < 3)
    throw new ApiError(
      400,
      'Add at least three distinct photos before finalizing. This only freezes the inputs; reconstruction quality needs many overlapping views.',
    );
  const manifestHash = digest(
    JSON.stringify({ schema: 1, frames: frames.map((frame) => frame.sha256).sort() }),
  );
  const { rows } = await tx.query(
    "UPDATE scan_sessions SET state='finalized',manifest_hash=$1,finalized_at=now() WHERE id=$2 RETURNING *",
    [manifestHash, id],
  );
  await audit(tx, restaurantId, actorId, 'scan.finalized', {
    scanId: id,
    frameCount: frames.length,
    manifestHash,
  });
  return { ...scanFromRow(rows[0]), frameCount: frames.length };
}
