import type { Queryable } from './db';
import { ApiError, idField } from './domain';
import { leaseIsCurrent, type JobLease } from './jobs';
export const ARTIFACT_PART_BYTES = 1024 * 1024;
export async function storeArtifactPart(
  tx: Queryable,
  lease: JobLease,
  kind: 'glb' | 'usdz',
  part: number,
  bytes: Uint8Array,
) {
  if (
    !Number.isInteger(part) ||
    part < 0 ||
    part >= 128 ||
    bytes.length > ARTIFACT_PART_BYTES ||
    !bytes.length
  )
    throw new Error('Invalid artifact part');
  if (!(await leaseIsCurrent(tx, lease))) throw new Error('Artifact lease expired');
  await tx.query(
    'INSERT INTO reconstruction_artifact_parts(job_id,generation,kind,part,bytes) VALUES($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING',
    [lease.id, lease.generation, kind, part, Buffer.from(bytes)],
  );
}
export async function artifactPart(
  tx: Queryable,
  restaurantId: string,
  jobValue: string,
  kind: string,
  partValue: string | null,
  scanId?: string,
) {
  const jobId = idField(jobValue);
  const part = partValue === null ? 0 : Number(partValue);
  if (!['glb', 'usdz'].includes(kind) || !Number.isInteger(part) || part < 0 || part >= 128)
    throw new ApiError(400, 'Invalid model part.');
  const row = (
    await tx.query(
      "SELECT * FROM reconstruction_jobs WHERE id=$1 AND restaurant_id=$2 AND state='ready_for_review'",
      [jobId, restaurantId],
    )
  ).rows[0];
  if (!row || (scanId && row.scan_id !== scanId)) throw new ApiError(404, 'Model not found.');
  const result = row.result as {
    leaseGeneration?: number;
    summary?: { outputs?: Record<string, { bytes: number; sha256: string; parts?: number }> };
  };
  const meta = result?.summary?.outputs?.[kind];
  if (!meta?.parts || part >= meta.parts || !result.leaseGeneration)
    throw new ApiError(404, 'Model not found.');
  const chunk = (
    await tx.query(
      'SELECT bytes FROM reconstruction_artifact_parts WHERE job_id=$1 AND generation=$2 AND kind=$3 AND part=$4',
      [jobId, result.leaseGeneration, kind, part],
    )
  ).rows[0];
  if (!chunk) throw new ApiError(404, 'Model part unavailable.');
  return new Response(new Uint8Array(chunk.bytes as Uint8Array), {
    headers: {
      'Content-Type': 'application/octet-stream',
      'Cache-Control': 'private, no-store',
      'X-Artifact-Parts': String(meta.parts),
      'X-Artifact-Bytes': String(meta.bytes),
      'X-Artifact-SHA256': meta.sha256,
    },
  });
}
