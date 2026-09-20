import { NextResponse } from 'next/server';
import { api } from '@/lib/server/http';
import { requireUser } from '@/lib/server/auth';
import { database } from '@/lib/server/db';
import { ApiError, idField } from '@/lib/server/domain';
import { cancelReconstruction, publicJob } from '@/lib/server/jobs';

type Context = { params: Promise<{ id: string }> };
export const GET = api(async (request, context: Context) => {
  const identity = await requireUser(request);
  const id = idField((await context.params).id);
  const row = (
    await (
      await database()
    ).query('SELECT * FROM reconstruction_jobs WHERE id=$1 AND restaurant_id=$2', [
      id,
      identity.restaurantId,
    ])
  ).rows[0];
  if (!row) throw new ApiError(404, 'Reconstruction not found.', 'NOT_FOUND');
  return NextResponse.json({ job: publicJob(row) });
});
export const DELETE = api(async (request, context: Context) => {
  const identity = await requireUser(request);
  const id = idField((await context.params).id);
  return NextResponse.json({
    job: await cancelReconstruction(await database(), identity.restaurantId, id),
    originalsPreserved: true,
  });
});
