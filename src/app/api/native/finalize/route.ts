import { NextResponse } from 'next/server';
import { api } from '@/lib/server/http';
import { database } from '@/lib/server/db';
import { withNativeCapture } from '@/lib/server/native-capture';
import { requestScanReconstruction } from '@/lib/server/automatic-reconstruction';
import { finalizeScan } from '@/lib/server/scans';
export const POST = api(
  async (request) => {
    const result = await withNativeCapture(
      await database(),
      request.headers.get('authorization'),
      async (tx, grant) => {
        const scan = await finalizeScan(
          tx,
          String(grant.scan_id),
          String(grant.restaurant_id),
          String(grant.created_by),
        );
        const reconstruction = await requestScanReconstruction(
          tx,
          String(grant.restaurant_id),
          String(grant.created_by),
          String(grant.scan_id),
        );
        return { scan, reconstruction };
      },
    );
    return NextResponse.json(result);
  },
  { nativeCapability: true },
);
