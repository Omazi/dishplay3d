import { frameMetadataHeader } from '@/lib/server/capture-manifest';
import { NextResponse } from 'next/server';
import { api, readBytes } from '@/lib/server/http';
import { digest, requireUser } from '@/lib/server/auth';
import { database } from '@/lib/server/db';
import { ApiError, idField, MAX_IMAGE_BYTES, validateImage } from '@/lib/server/domain';
import { lockRestaurant } from '@/lib/server/catalogue';
import { appendScanFrame } from '@/lib/server/scans';

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
    return appendScanFrame(
      tx,
      id,
      identity.restaurantId,
      bytes,
      mime,
      frameMetadataHeader(request),
    );
  });
  return NextResponse.json(result, { status: result.duplicate ? 200 : 201 });
});
