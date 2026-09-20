import type { Database, Queryable } from './db';
import { ApiError } from './domain';
import { enqueueReconstruction, freshWorkers, publicJob } from './jobs';

export async function requestScanReconstruction(
  tx: Queryable,
  restaurantId: string,
  actorId: string,
  scanId: string,
) {
  // Called after finalization. A disconnected PC leaves an honest durable queued job.
  if (process.env.ENABLE_RECONSTRUCTION !== 'true' || !process.env.DATABASE_URL)
    return { state: 'unavailable', code: 'WORKER_NOT_CONFIGURED' };
  const count = Number(
    (
      await tx.query('SELECT count(*)::integer AS count FROM scan_frames WHERE scan_id=$1', [
        scanId,
      ])
    ).rows[0].count,
  );
  try {
    const db: Database = { query: tx.query.bind(tx), transaction: async (work) => work(tx) };
    return await enqueueReconstruction(
      db,
      restaurantId,
      actorId,
      scanId,
      { maxImages: Math.max(24, count) },
      true,
    );
  } catch (error) {
    // Do not roll back a successfully saved capture when admission requires attention.
    if (error instanceof ApiError) return { state: 'unavailable', code: error.code };
    throw error;
  }
}
export async function scanReconstructionStatus(
  tx: Queryable,
  restaurantId: string,
  scanId: string,
) {
  const row = (
    await tx.query(
      'SELECT * FROM reconstruction_jobs WHERE restaurant_id=$1 AND scan_id=$2 ORDER BY created_at DESC LIMIT 1',
      [restaurantId, scanId],
    )
  ).rows[0];
  const enabled = process.env.ENABLE_RECONSTRUCTION === 'true' && Boolean(process.env.DATABASE_URL);
  return {
    job: row ? publicJob(row) : null,
    enabled,
    workerAvailable: enabled && (await freshWorkers(tx)).length > 0,
  };
}
