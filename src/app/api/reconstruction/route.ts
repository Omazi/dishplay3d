import { api, jsonBody } from '@/lib/server/http';
import { requireUser } from '@/lib/server/auth';
import { ApiError } from '@/lib/server/domain';
import { database } from '@/lib/server/db';
import { NextResponse } from 'next/server';
import { enqueueReconstruction, freshWorkers, listJobs } from '@/lib/server/jobs';

export const GET = api(async (request) => {
  const identity = await requireUser(request);
  const db = await database();
  const enabled = process.env.ENABLE_RECONSTRUCTION === 'true' && Boolean(process.env.DATABASE_URL);
  return NextResponse.json({
    jobs: await listJobs(db, identity.restaurantId),
    enabled,
    workerAvailable: enabled && (await freshWorkers(db)).length > 0,
  });
});

export const POST = api(async (request) => {
  const identity = await requireUser(request);
  if (process.env.ENABLE_RECONSTRUCTION !== 'true' || !process.env.DATABASE_URL) {
    throw new ApiError(
      503,
      'Reconstruction is not enabled on this deployment. Your uploaded photos and current model are preserved. A separately configured PostgreSQL worker is required.',
      'WORKER_UNAVAILABLE',
    );
  }
  const db = await database();
  if (!(await freshWorkers(db)).length)
    throw new ApiError(
      503,
      'No reconstruction worker has a fresh heartbeat. Your photos and current model are preserved.',
      'WORKER_UNAVAILABLE',
    );
  const body = await jsonBody(request);
  return NextResponse.json(
    await enqueueReconstruction(
      db,
      identity.restaurantId,
      identity.user.id,
      body.scanId,
      body.settings,
    ),
    { status: 202 },
  );
});
