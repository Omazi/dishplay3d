import { type Queryable, type Row } from './db';
import { digest, newId } from './auth';
import { audit } from './catalogue';
import { saveMedia } from './media';
import { ApiError } from './domain';
import { imageDimensions } from '../image-validation';
import { captureMetadata, canonicalJSON, scanInputs } from './capture-manifest';

export function scanFromRow(row: Row) {
  return {
    id: String(row.id),
    dishId: String(row.dish_id),
    state: String(row.state),
    frameCount: Number(row.frame_count || 0),
    createdAt: new Date(String(row.created_at)).toISOString(),
    sourceType: String(row.source_type ?? 'photos'),
    manifestSchema: Number(row.manifest_schema ?? 1),
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
    'SELECT * FROM scan_frames WHERE scan_id=$1 ORDER BY frame_index ASC NULLS LAST,created_at,id',
    [scanId],
  );
  return rows.map((row) => ({
    id: String(row.id),
    mediaId: String(row.media_id),
    sha256: String(row.sha256),
    url: `/api/media/${row.media_id}`,
    frameIndex: row.frame_index == null ? null : Number(row.frame_index),
    timestampMs: row.timestamp_ms == null ? null : Number(row.timestamp_ms),
    width: row.width == null ? null : Number(row.width),
    height: row.height == null ? null : Number(row.height),
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
  suppliedMetadata?: Record<string, unknown>,
) {
  const sha256 = digest(bytes);
  const scan = await ownedScan(tx, id, restaurantId, true);
  if (scan.state !== 'capturing')
    throw new ApiError(
      409,
      'This capture is closed. Start another capture to add new photos.',
      'SCAN_CLOSED',
    );
  const metadata = captureMetadata(suppliedMetadata ?? {});
  const ordered = suppliedMetadata !== undefined;
  const frameIndex = ordered ? metadata.frameIndex : null;
  const timestampMs = ordered ? metadata.timestampMs : null;
  if (
    ordered &&
    (!Number.isInteger(frameIndex) ||
      Number(frameIndex) < 0 ||
      Number(frameIndex) > 1_000_000 ||
      typeof timestampMs !== 'number' ||
      !Number.isFinite(timestampMs) ||
      timestampMs < 0 ||
      timestampMs >= 86400000)
  )
    throw new ApiError(
      400,
      'Video frames require frameIndex and timestampMs.',
      'INVALID_FRAME_SEQUENCE',
    );
  const hasFrames =
    (await tx.query('SELECT id FROM scan_frames WHERE scan_id=$1 LIMIT 1', [id])).rows.length > 0;
  const hasVideo =
    (await tx.query('SELECT id FROM capture_videos WHERE scan_id=$1', [id])).rows.length > 0;
  if (
    hasVideo ||
    (hasFrames && ordered !== (scan.source_type === 'video')) ||
    (!ordered && scan.source_type === 'video')
  )
    throw new ApiError(
      409,
      'Cannot mix photo, ordered frame and raw video sources.',
      'MIXED_CAPTURE_SOURCES',
    );
  if (ordered)
    await tx.query("UPDATE scan_sessions SET source_type='video',manifest_schema=2 WHERE id=$1", [
      id,
    ]);
  const duplicate = (
    await tx.query(
      ordered
        ? 'SELECT * FROM scan_frames WHERE scan_id=$1 AND frame_index=$2'
        : 'SELECT * FROM scan_frames WHERE scan_id=$1 AND sha256=$2',
      [id, ordered ? frameIndex : sha256],
    )
  ).rows[0];
  if (duplicate) {
    if (
      ordered &&
      (duplicate.sha256 !== sha256 ||
        Number(duplicate.timestamp_ms) !== timestampMs ||
        canonicalJSON(duplicate.metadata) !== canonicalJSON(metadata))
    )
      throw new ApiError(
        409,
        'Frame index already belongs to different content or metadata.',
        'FRAME_INDEX_CONFLICT',
      );
    return {
      frame: {
        id: String(duplicate.id),
        mediaId: String(duplicate.media_id),
        sha256,
        url: `/api/media/${duplicate.media_id}`,
      },
      duplicate: true,
    };
  }
  const count = (
    await tx.query('SELECT count(*)::integer AS count FROM scan_frames WHERE scan_id=$1', [id])
  ).rows[0];
  if (Number(count.count) >= 150) throw new ApiError(400, 'A capture supports up to 150 photos.');
  const asset = await saveMedia(tx, restaurantId, bytes, mime);
  const frameId = newId();
  const dimensions = imageDimensions(bytes, mime);
  await tx.query(
    'INSERT INTO scan_frames(id,scan_id,media_id,sha256,frame_index,timestamp_ms,width,height,metadata) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)',
    [
      frameId,
      id,
      asset.id,
      sha256,
      frameIndex,
      timestampMs,
      dimensions?.width ?? null,
      dimensions?.height ?? null,
      JSON.stringify(metadata),
    ],
  );
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
  const inputs = await scanInputs(tx, previous);
  if (!inputs.video && frames.length < 3)
    throw new ApiError(
      400,
      'Add at least three distinct photos before finalizing. This only freezes the inputs; reconstruction quality needs many overlapping views.',
    );
  const manifestHash = inputs.hash;
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
