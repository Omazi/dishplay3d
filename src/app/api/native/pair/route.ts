import { NextResponse } from 'next/server';
import { api, jsonBody } from '@/lib/server/http';
import { database } from '@/lib/server/db';
import { claimCaptureLink, limitPairing } from '@/lib/server/native-capture';
export const POST = api(
  async (request) => {
    const db = await database();
    await limitPairing(
      db,
      request.headers.get('x-forwarded-for')?.split(',')[0]?.trim() || 'local',
    );
    const body = await jsonBody(request);
    return NextResponse.json(await claimCaptureLink(db, body.code, body.deviceSecret));
  },
  { nativeCapability: true },
);
