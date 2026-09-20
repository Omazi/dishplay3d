import { NextResponse } from 'next/server';
import { api } from '@/lib/server/http';
import { database } from '@/lib/server/db';
import { withNativeCapture, captureSnapshot } from '@/lib/server/native-capture';
export const GET = api(
  async (request) =>
    NextResponse.json(
      await withNativeCapture(
        await database(),
        request.headers.get('authorization'),
        captureSnapshot,
      ),
    ),
  { nativeCapability: true },
);
