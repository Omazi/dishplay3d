import { NextResponse } from 'next/server';
import { api, readBytes } from '@/lib/server/http';
import { digest, newId, requireUser } from '@/lib/server/auth';
import { database } from '@/lib/server/db';
import { ApiError, idField, MAX_IMAGE_BYTES, validateImage } from '@/lib/server/domain';
import { lockRestaurant } from '@/lib/server/catalogue';
import { ownedScan } from '@/lib/server/scans';
import { saveMedia } from '@/lib/server/media';

export const POST = api(async (request, context: { params: Promise<{ id: string }> }) => {
  const identity = await requireUser(request);
  const id = idField((await context.params).id);
  const bytes = await readBytes(request, MAX_IMAGE_BYTES);
  const mime = request.headers.get('content-type')?.split(';')[0] || '';
  validateImage(bytes, mime);
  const sha256 = digest(bytes);
  const expected = request.headers.get('x-content-sha256');
  if (expected && (!/^[a-f0-9]{64}$/.test(expected) || expected !== sha256))
    throw new ApiError(
      400,
      'The photo checksum does not match. Please upload it again.',
      'CHECKSUM_MISMATCH',
    );
  const result = await (
    await database()
  ).transaction(async (tx) => {
    await lockRestaurant(tx, identity.restaurantId);
    const scan = await ownedScan(tx, id, identity.restaurantId, true);
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
    const asset = await saveMedia(tx, identity.restaurantId, bytes, mime);
    const frameId = newId();
    await tx.query('INSERT INTO scan_frames(id,scan_id,media_id,sha256) VALUES($1,$2,$3,$4)', [
      frameId,
      id,
      asset.id,
      sha256,
    ]);
    return { frame: { id: frameId, mediaId: asset.id, sha256, url: asset.url }, duplicate: false };
  });
  return NextResponse.json(result, { status: result.duplicate ? 200 : 201 });
});
