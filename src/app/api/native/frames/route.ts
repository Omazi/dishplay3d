import { frameMetadataHeader } from '@/lib/server/capture-manifest';
import { NextResponse } from 'next/server';
import { api, readBytes } from '@/lib/server/http';
import { database } from '@/lib/server/db';
import { digest } from '@/lib/server/auth';
import { withNativeCapture } from '@/lib/server/native-capture';
import { appendScanFrame } from '@/lib/server/scans';
import { ApiError, MAX_IMAGE_BYTES, validateImage } from '@/lib/server/domain';
export const POST = api(
  async (request) => {
    // Reject invalid capability before consuming an image body.
    await withNativeCapture(
      await database(),
      request.headers.get('authorization'),
      async () => undefined,
    );
    const bytes = await readBytes(request, MAX_IMAGE_BYTES);
    const mime = request.headers.get('content-type')?.split(';')[0] || '';
    validateImage(bytes, mime);
    if (request.headers.get('x-content-sha256') !== digest(bytes))
      throw new ApiError(400, 'The photo checksum does not match.', 'CHECKSUM_MISMATCH');
    const result = await withNativeCapture(
      await database(),
      request.headers.get('authorization'),
      (tx, grant) =>
        appendScanFrame(
          tx,
          String(grant.scan_id),
          String(grant.restaurant_id),
          bytes,
          mime,
          frameMetadataHeader(request),
        ),
    );
    return NextResponse.json(
      { sha256: result.frame.sha256, duplicate: result.duplicate },
      { status: result.duplicate ? 200 : 201 },
    );
  },
  { nativeCapability: true },
);
