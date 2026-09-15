import { NextResponse } from 'next/server';
import { api, readBytes } from '@/lib/server/http';
import { requireUser } from '@/lib/server/auth';
import { database } from '@/lib/server/db';
import { MAX_IMAGE_BYTES } from '@/lib/server/domain';
import { lockRestaurant } from '@/lib/server/catalogue';
import { saveMedia } from '@/lib/server/media';

export const POST = api(async (request) => {
  const identity = await requireUser(request);
  const bytes = await readBytes(request, MAX_IMAGE_BYTES);
  const mime = request.headers.get('content-type')?.split(';')[0] || '';
  const asset = await (
    await database()
  ).transaction(async (tx) => {
    await lockRestaurant(tx, identity.restaurantId);
    return saveMedia(tx, identity.restaurantId, bytes, mime);
  });
  return NextResponse.json(asset, { status: 201 });
});
