import { NextResponse } from 'next/server';
import { api } from '@/lib/server/http';
import { database } from '@/lib/server/db';
import { withNativeCapture } from '@/lib/server/native-capture';
import {
  requestScanReconstruction,
  scanReconstructionStatus,
} from '@/lib/server/automatic-reconstruction';
export const GET = api(
  async (request) =>
    NextResponse.json(
      await withNativeCapture(await database(), request.headers.get('authorization'), (tx, grant) =>
        scanReconstructionStatus(tx, String(grant.restaurant_id), String(grant.scan_id)),
      ),
    ),
  { nativeCapability: true },
);
export const POST = api(
  async (request) =>
    NextResponse.json(
      await withNativeCapture(await database(), request.headers.get('authorization'), (tx, grant) =>
        requestScanReconstruction(
          tx,
          String(grant.restaurant_id),
          String(grant.created_by),
          String(grant.scan_id),
        ),
      ),
    ),
  { nativeCapability: true },
);
