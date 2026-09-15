import { type Queryable } from './db';
import { ApiError, validateImage } from './domain';
import { digest, newId } from './auth';

export const MAX_RESTAURANT_MEDIA_BYTES = 100 * 1024 * 1024;
export async function saveMedia(
  tx: Queryable,
  restaurantId: string,
  bytes: Uint8Array,
  mime: string,
): Promise<{ id: string; sha256: string; url: string }> {
  validateImage(bytes, mime);
  const sha256 = digest(bytes);
  const existing = (
    await tx.query('SELECT id FROM media_assets WHERE restaurant_id=$1 AND sha256=$2', [
      restaurantId,
      sha256,
    ])
  ).rows[0];
  if (existing) return { id: String(existing.id), sha256, url: `/api/media/${existing.id}` };
  const total = (
    await tx.query(
      'SELECT COALESCE(sum(byte_size),0) AS total FROM media_assets WHERE restaurant_id=$1',
      [restaurantId],
    )
  ).rows[0];
  if (Number(total.total) + bytes.byteLength > MAX_RESTAURANT_MEDIA_BYTES)
    throw new ApiError(
      413,
      'The restaurant has reached its 100 MB pilot media allowance. Export your originals and contact the operator before adding more.',
    );
  const id = newId();
  await tx.query(
    'INSERT INTO media_assets(id,restaurant_id,mime_type,byte_size,sha256,content_base64) VALUES($1,$2,$3,$4,$5,$6)',
    [id, restaurantId, mime, bytes.byteLength, sha256, Buffer.from(bytes).toString('base64')],
  );
  return { id, sha256, url: `/api/media/${id}` };
}
