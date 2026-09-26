import { createHash } from 'node:crypto';
import type { Queryable, Row } from './db';
import { ApiError } from './domain';

export const captureHash = (value: string | Uint8Array) =>
  createHash('sha256').update(value).digest('hex');
// Canonical JSON for metadata: PostgreSQL jsonb may reorder object keys.
export function canonicalJSON(value: unknown): string {
  if (value === null || typeof value !== 'object') {
    if (typeof value === 'number' && !Number.isFinite(value))
      throw new ApiError(400, 'Metadata numbers must be finite.');
    const encoded = JSON.stringify(value);
    if (encoded === undefined) throw new ApiError(400, 'Metadata must contain only JSON values.');
    return encoded;
  }
  if (Array.isArray(value)) return `[${value.map(canonicalJSON).join(',')}]`;
  return `{${Object.keys(value)
    .sort()
    .map(
      (key) => `${JSON.stringify(key)}:${canonicalJSON((value as Record<string, unknown>)[key])}`,
    )
    .join(',')}}`;
}
export function captureMetadata(value: unknown = {}): Record<string, unknown> {
  if (
    !value ||
    typeof value !== 'object' ||
    Array.isArray(value) ||
    canonicalJSON(value).length > 16_384
  )
    throw new ApiError(
      400,
      'Capture metadata must be an object of at most 16 KiB.',
      'INVALID_CAPTURE_METADATA',
    );
  const encoded = canonicalJSON(value);
  return JSON.parse(encoded);
}
export function frameMetadataHeader(request: Request): Record<string, unknown> | undefined {
  const raw = request.headers.get('x-frame-metadata');
  if (raw === null) return undefined;
  try {
    return captureMetadata(JSON.parse(raw));
  } catch {
    throw new ApiError(400, 'Invalid x-frame-metadata JSON.', 'INVALID_CAPTURE_METADATA');
  }
}
export function scanManifest(scan: Row, frames: Row[], video?: Row) {
  if (Number(scan.manifest_schema ?? 1) === 1) {
    if (scan.source_type && scan.source_type !== 'photos')
      throw new ApiError(409, 'Video requires manifest v2.', 'INPUT_CHANGED');
    return { schema: 1, frames: frames.map((frame) => String(frame.sha256)).sort() };
  }
  const ordered = [...frames].sort((a, b) => Number(a.frame_index) - Number(b.frame_index));
  let lastIndex = -1,
    lastTime = -1;
  for (const frame of ordered) {
    const index = Number(frame.frame_index),
      time = Number(frame.timestamp_ms);
    if (
      frame.frame_index == null ||
      frame.timestamp_ms == null ||
      !Number.isInteger(index) ||
      index <= lastIndex ||
      !Number.isFinite(time) ||
      time < lastTime ||
      time < 0 ||
      time >= 86400000 ||
      !(Number(frame.width) > 0 && Number(frame.height) > 0)
    )
      throw new ApiError(
        409,
        'Video frames require unique increasing indexes, monotonic timestamps and dimensions.',
        'INVALID_FRAME_SEQUENCE',
      );
    lastIndex = index;
    lastTime = time;
  }
  if (video && frames.length)
    throw new ApiError(409, 'Use either raw video or uploaded frames.', 'MIXED_CAPTURE_SOURCES');
  return {
    schema: 2,
    sourceType: 'video',
    frames: ordered.map((frame) => ({
      frameIndex: Number(frame.frame_index),
      timestampMs: Number(frame.timestamp_ms),
      sha256: String(frame.sha256),
      width: Number(frame.width),
      height: Number(frame.height),
      metadata: frame.metadata ?? {},
    })),
    captureMetadataHash: captureHash(canonicalJSON(scan.capture_metadata ?? {})),
    ...(video
      ? {
          video: {
            sha256: String(video.sha256),
            bytes: Number(video.byte_size),
            mime: String(video.mime_type),
          },
        }
      : {}),
  };
}
export function manifestDigest(manifest: ReturnType<typeof scanManifest>): string {
  // schema 1 MUST retain original property order and serialization.
  return captureHash(manifest.schema === 1 ? JSON.stringify(manifest) : canonicalJSON(manifest));
}
export async function scanInputs(db: Queryable, scan: Row) {
  const frames = (
    await db.query(
      `SELECT f.*,a.mime_type,a.byte_size FROM scan_frames f JOIN media_assets a ON a.id=f.media_id
    WHERE f.scan_id=$1 AND a.restaurant_id=$2 ORDER BY f.frame_index ASC NULLS LAST,f.sha256`,
      [scan.id, scan.restaurant_id],
    )
  ).rows;
  const video = (
    await db.query('SELECT * FROM capture_videos WHERE scan_id=$1 AND restaurant_id=$2', [
      scan.id,
      scan.restaurant_id,
    ])
  ).rows[0];
  const manifest = scanManifest(scan, frames, video);
  return { frames, video, manifest, hash: manifestDigest(manifest) };
}
