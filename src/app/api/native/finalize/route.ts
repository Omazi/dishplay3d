import { NextResponse } from 'next/server';
import { api } from '@/lib/server/http';
import { database } from '@/lib/server/db';
import { withNativeCapture } from '@/lib/server/native-capture';
import { finalizeScan } from '@/lib/server/scans';
export const POST = api(
  async (request) => {
    const scan = await withNativeCapture(
      await database(),
      request.headers.get('authorization'),
      (tx, grant) =>
        finalizeScan(
          tx,
          String(grant.scan_id),
          String(grant.restaurant_id),
          String(grant.created_by),
        ),
    );
    return NextResponse.json({ scan });
  },
  { nativeCapability: true },
);
