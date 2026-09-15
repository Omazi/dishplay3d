import { api } from '@/lib/server/http';
import { requireUser } from '@/lib/server/auth';
import { ApiError } from '@/lib/server/domain';
import { database } from '@/lib/server/db';
import { NextResponse } from 'next/server';

export const GET = api(async (request) => {
  const identity = await requireUser(request);
  const { rows } = await (
    await database()
  ).query(
    'SELECT id,scan_id AS "scanId",engine,state,attempts,error_code AS "errorCode",created_at AS "createdAt",updated_at AS "updatedAt" FROM reconstruction_jobs WHERE restaurant_id=$1 ORDER BY created_at DESC LIMIT 100',
    [identity.restaurantId],
  );
  return NextResponse.json({ jobs: rows });
});

export const POST = api(async (request) => {
  await requireUser(request);
  throw new ApiError(
    503,
    'Reconstruction is not connected to this deployment. Your uploaded photos and current model are preserved. Export the capture and process it with the documented local worker.',
    'WORKER_UNAVAILABLE',
  );
});
