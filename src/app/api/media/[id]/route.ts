import { api } from '@/lib/server/http';
import { currentUser } from '@/lib/server/auth';
import { database } from '@/lib/server/db';
import { ApiError, idField } from '@/lib/server/domain';

export const GET = api(async (request, context: { params: Promise<{ id: string }> }) => {
  const id = idField((await context.params).id);
  const db = await database();
  const asset = (
    await db.query(
      `SELECT a.*, EXISTS(SELECT 1 FROM published_media p WHERE p.media_id=a.id) AS public FROM media_assets a WHERE a.id=$1`,
      [id],
    )
  ).rows[0];
  if (!asset) throw new ApiError(404, 'Image not found.', 'NOT_FOUND');
  const isPublic = Boolean(asset.public);
  if (!isPublic) {
    const identity = await currentUser(request);
    if (!identity || identity.restaurantId !== asset.restaurant_id)
      throw new ApiError(404, 'Image not found.', 'NOT_FOUND');
  }
  const bytes = new Uint8Array(Buffer.from(String(asset.content_base64), 'base64'));
  return new Response(bytes, {
    headers: {
      'Content-Type': String(asset.mime_type),
      'Content-Length': String(asset.byte_size),
      'Cache-Control': isPublic ? 'public, max-age=31536000, immutable' : 'private, no-store',
      'Content-Disposition': `inline; filename="${id}.${asset.mime_type === 'image/jpeg' ? 'jpg' : asset.mime_type === 'image/png' ? 'png' : 'webp'}"`,
      ETag: `"${asset.sha256}"`,
      'X-Content-Type-Options': 'nosniff',
    },
  });
});
