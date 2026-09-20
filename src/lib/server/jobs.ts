import { createHash, randomBytes, randomUUID } from 'node:crypto';
import type { Database, Queryable, Row } from './db';
import { ApiError, idField, integerField, textField } from './domain';

export const ENGINE_PINS = {
  colmap: '3.11.1',
  openmvs: '2.3.0',
  blender: '4.5.13',
  pillow: '12.3.0',
} as const;
export const RECONSTRUCTION_ENGINE = 'colmap3.11.1-openmvs2.3.0-blender4.5.13-pillow12.3.0:bridge1';
export const LEASE_SECONDS = 90;
export const HEARTBEAT_FRESH_SECONDS = 45;
export interface ReconstructionSettings {
  maxImages: number;
  longEdge: number;
  memoryMiB: number;
  diskMiB: number;
  stageSeconds: number;
  scaleMetersPerUnit: number | null;
  scaleReference: string | null;
  openMvsCudaBuild: boolean;
}
export interface WorkerCapabilities {
  maxImages: number;
  longEdge: number;
  memoryMiB: number;
  diskMiB: number;
  stageSeconds: number;
  openMvsCudaBuild: boolean;
}
export interface JobLease {
  id: string;
  restaurantId: string;
  scanId: string;
  inputHash: string;
  settings: ReconstructionSettings;
  token: string;
  generation: number;
  workerId: string;
  attempts: number;
}
const sha256 = (value: string) => createHash('sha256').update(value).digest('hex');

function bounded(value: unknown, name: string, minimum: number, maximum: number): number {
  const parsed = integerField(value, name, maximum);
  if (parsed < minimum)
    throw new ApiError(400, `${name} must be between ${minimum} and ${maximum}.`);
  return parsed;
}
export function normalizeSettings(value: unknown = {}): ReconstructionSettings {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    throw new ApiError(400, 'Reconstruction settings must be an object.');
  const settings = value as Record<string, unknown>;
  const keys = [
    'maxImages',
    'longEdge',
    'memoryMiB',
    'diskMiB',
    'stageSeconds',
    'scaleMetersPerUnit',
    'scaleReference',
    'openMvsCudaBuild',
  ];
  if (Object.keys(settings).some((key) => !keys.includes(key)))
    throw new ApiError(400, 'An unsupported reconstruction setting was supplied.');
  const scale = settings.scaleMetersPerUnit ?? null;
  const reference =
    settings.scaleReference == null
      ? null
      : textField(settings.scaleReference, 'Measured scale reference', 240, true);
  if (
    scale !== null &&
    (typeof scale !== 'number' || !Number.isFinite(scale) || scale <= 0 || scale > 1000)
  )
    throw new ApiError(400, 'Scale must be a finite positive number no greater than 1000.');
  if ((scale === null) !== (reference === null))
    throw new ApiError(400, 'Supply a measured scale value and reference together.');
  if (settings.openMvsCudaBuild !== undefined && typeof settings.openMvsCudaBuild !== 'boolean')
    throw new ApiError(400, 'OpenMVS build selection must be a boolean.');
  return {
    maxImages: bounded(settings.maxImages ?? 24, 'Maximum image count', 3, 40),
    longEdge: bounded(settings.longEdge ?? 1600, 'Image long edge', 320, 1600),
    memoryMiB: bounded(settings.memoryMiB ?? 1536, 'Memory limit MiB', 512, 2048),
    diskMiB: bounded(settings.diskMiB ?? 2048, 'Disk limit MiB', 256, 4096),
    stageSeconds: bounded(settings.stageSeconds ?? 900, 'Stage time limit seconds', 30, 1800),
    scaleMetersPerUnit: scale as number | null,
    scaleReference: reference,
    openMvsCudaBuild: settings.openMvsCudaBuild === true,
  };
}
export function queueIdentity(manifestHash: string, settings: ReconstructionSettings): string {
  return sha256(
    JSON.stringify({
      schema: 1,
      manifestHash,
      engine: RECONSTRUCTION_ENGINE,
      settings: normalizeSettings(settings),
    }),
  );
}
export function workerCanRun(
  capabilities: WorkerCapabilities,
  settings: ReconstructionSettings,
): boolean {
  return (
    ['maxImages', 'longEdge', 'memoryMiB', 'diskMiB', 'stageSeconds'].every(
      (key) =>
        Number(capabilities[key as keyof WorkerCapabilities]) >=
        Number(settings[key as keyof ReconstructionSettings]),
    ) && capabilities.openMvsCudaBuild === settings.openMvsCudaBuild
  );
}
export async function workerHeartbeat(
  db: Queryable,
  id: string,
  capabilities: WorkerCapabilities,
  ready: boolean,
): Promise<void> {
  await db.query(
    `INSERT INTO reconstruction_workers(id,engine,capabilities,ready) VALUES($1,$2,$3,$4)
    ON CONFLICT(id) DO UPDATE SET engine=EXCLUDED.engine,capabilities=EXCLUDED.capabilities,ready=EXCLUDED.ready,last_seen_at=clock_timestamp()`,
    [id, RECONSTRUCTION_ENGINE, JSON.stringify(capabilities), ready],
  );
}
export async function freshWorkers(db: Queryable): Promise<Row[]> {
  return (
    await db.query(
      `SELECT id,capabilities FROM reconstruction_workers WHERE engine=$1 AND ready=true
    AND last_seen_at > clock_timestamp()-interval '45 seconds'`,
      [RECONSTRUCTION_ENGINE],
    )
  ).rows;
}
export function publicJob(row: Row) {
  const result =
    row.result && typeof row.result === 'object' ? (row.result as Record<string, unknown>) : null;
  return {
    id: String(row.id),
    scanId: String(row.scan_id),
    engine: String(row.engine),
    state: String(row.state),
    attempts: Number(row.attempts),
    maxAttempts: Number(row.max_attempts),
    errorCode: row.error_code ? String(row.error_code) : null,
    stage: row.stage ? String(row.stage) : null,
    createdAt: new Date(String(row.created_at)).toISOString(),
    updatedAt: new Date(String(row.updated_at)).toISOString(),
    review: result?.summary ?? null,
  };
}
export async function listJobs(db: Queryable, restaurantId: string) {
  const { rows } = await db.query(
    'SELECT * FROM reconstruction_jobs WHERE restaurant_id=$1 ORDER BY created_at DESC LIMIT 100',
    [restaurantId],
  );
  return rows.map(publicJob);
}
export async function enqueueReconstruction(
  db: Database,
  restaurantId: string,
  actorId: string,
  scanIdValue: unknown,
  settingsValue: unknown = {},
  allowOffline = false,
) {
  const scanId = idField(scanIdValue, 'Capture ID');
  const settings = normalizeSettings(settingsValue);
  return db.transaction(async (tx) => {
    await tx.query('SELECT id FROM restaurants WHERE id=$1 FOR UPDATE', [restaurantId]);
    const scan = (
      await tx.query('SELECT * FROM scan_sessions WHERE id=$1 AND restaurant_id=$2 FOR UPDATE', [
        scanId,
        restaurantId,
      ])
    ).rows[0];
    if (!scan) throw new ApiError(404, 'Capture not found.', 'NOT_FOUND');
    if (scan.state !== 'finalized' || !scan.manifest_hash)
      throw new ApiError(
        409,
        'Finalize the capture before requesting reconstruction.',
        'SCAN_NOT_FINALIZED',
      );
    const frames = (
      await tx.query(
        `SELECT f.sha256,a.mime_type FROM scan_frames f JOIN media_assets a ON a.id=f.media_id WHERE f.scan_id=$1 ORDER BY f.sha256`,
        [scanId],
      )
    ).rows;
    if (frames.length < 3 || frames.length > settings.maxImages)
      throw new ApiError(
        400,
        `This worker request accepts 3–${settings.maxImages} photos; this capture contains ${frames.length}. Create a capture within that budget. No photos were discarded.`,
        'FRAME_BUDGET_EXCEEDED',
      );
    if (frames.some((frame) => !['image/jpeg', 'image/png'].includes(String(frame.mime_type))))
      throw new ApiError(
        400,
        'This reconstruction engine accepts JPEG and PNG inputs. Preserve this capture and create a JPEG/PNG capture for reconstruction.',
        'UNSUPPORTED_RECONSTRUCTION_IMAGE',
      );
    const manifestHash = sha256(
      JSON.stringify({ schema: 1, frames: frames.map((frame) => String(frame.sha256)).sort() }),
    );
    if (manifestHash !== scan.manifest_hash)
      throw new ApiError(
        409,
        'The finalized capture manifest does not match its frames.',
        'INPUT_CHANGED',
      );
    const workers = await freshWorkers(tx);
    if (
      !allowOffline &&
      !workers.some((worker) =>
        workerCanRun(worker.capabilities as unknown as WorkerCapabilities, settings),
      )
    )
      throw new ApiError(
        503,
        'No recently connected worker supports this image and resource budget. Your photos and current model are preserved.',
        'WORKER_UNAVAILABLE',
      );
    const hash = queueIdentity(manifestHash, settings);
    const existing = (
      await tx.query(
        'SELECT * FROM reconstruction_jobs WHERE restaurant_id=$1 AND input_hash=$2 AND engine=$3',
        [restaurantId, hash, RECONSTRUCTION_ENGINE],
      )
    ).rows[0];
    if (existing)
      return { id: String(existing.id), state: String(existing.state), deduplicated: true };
    const pending = (
      await tx.query(
        "SELECT count(*)::integer AS count FROM reconstruction_jobs WHERE restaurant_id=$1 AND state IN ('queued','running')",
        [restaurantId],
      )
    ).rows[0];
    if (Number(pending.count) >= 3)
      throw new ApiError(
        429,
        'This restaurant already has three pending reconstructions. Wait or cancel a queued job.',
        'QUEUE_LIMIT',
      );
    const id = randomUUID();
    await tx.query(
      `INSERT INTO reconstruction_jobs(id,restaurant_id,scan_id,input_hash,engine,settings,max_attempts) VALUES($1,$2,$3,$4,$5,$6,2)`,
      [id, restaurantId, scanId, hash, RECONSTRUCTION_ENGINE, JSON.stringify(settings)],
    );
    await tx.query(
      'INSERT INTO audit_events(id,restaurant_id,actor_id,action,details) VALUES($1,$2,$3,$4,$5)',
      [
        randomUUID(),
        restaurantId,
        actorId,
        'reconstruction.queued',
        JSON.stringify({ jobId: id, scanId, engine: RECONSTRUCTION_ENGINE }),
      ],
    );
    return { id, state: 'queued', deduplicated: false };
  });
}
export async function cancelReconstruction(db: Database, restaurantId: string, id: string) {
  return db.transaction(async (tx) => {
    const current = (
      await tx.query(
        'SELECT * FROM reconstruction_jobs WHERE id=$1 AND restaurant_id=$2 FOR UPDATE',
        [id, restaurantId],
      )
    ).rows[0];
    if (!current) throw new ApiError(404, 'Reconstruction not found.', 'NOT_FOUND');
    if (current.state === 'cancelled') return publicJob(current);
    if (!['queued', 'running'].includes(String(current.state)))
      throw new ApiError(
        409,
        'This reconstruction already ended. Its originals and any generated outputs remain available.',
        'JOB_TERMINAL',
      );
    const row = (
      await tx.query(
        `UPDATE reconstruction_jobs SET state='cancelled',error_code='CANCELLED_BY_OWNER',stage=NULL,lease_token=NULL,lease_until=NULL,worker_id=NULL,lease_generation=lease_generation+1,updated_at=clock_timestamp() WHERE id=$1 RETURNING *`,
        [id],
      )
    ).rows[0];
    return publicJob(row);
  });
}
export async function claimJob(
  db: Database,
  workerId: string,
  capabilities: WorkerCapabilities,
): Promise<JobLease | null> {
  return db.transaction(async (tx) => {
    // Cancellation fences database writes immediately, but capacity remains occupied
    // until the old process acknowledges stopping or its lease plus stop grace expires.
    const capacity = (
      await tx.query(
        'SELECT *,blocked_until>clock_timestamp() AS blocked FROM reconstruction_capacity WHERE id=1 FOR UPDATE',
      )
    ).rows[0];
    if (capacity?.blocked) return null;
    await tx.query(`UPDATE reconstruction_jobs SET state=CASE WHEN attempts<max_attempts THEN 'queued' ELSE 'failed' END,
      error_code='LEASE_EXPIRED',lease_token=NULL,lease_until=NULL,worker_id=NULL,stage=NULL,updated_at=clock_timestamp()
      WHERE state='running' AND lease_until <= clock_timestamp()`);
    if (
      (
        await tx.query(
          "SELECT id FROM reconstruction_jobs WHERE state='running' AND lease_until>clock_timestamp() LIMIT 1",
        )
      ).rows[0]
    )
      return null;
    const registration = (
      await tx.query(
        `SELECT id FROM reconstruction_workers WHERE id=$1 AND engine=$2 AND ready=true AND last_seen_at>clock_timestamp()-interval '45 seconds'`,
        [workerId, RECONSTRUCTION_ENGINE],
      )
    ).rows[0];
    if (!registration) return null;
    const rows = (
      await tx.query(
        `SELECT * FROM reconstruction_jobs WHERE state='queued' AND engine=$1 AND available_at<=clock_timestamp()
      AND attempts<max_attempts ORDER BY created_at,id LIMIT 100 FOR UPDATE SKIP LOCKED`,
        [RECONSTRUCTION_ENGINE],
      )
    ).rows;
    const candidate = rows.find((row) =>
      workerCanRun(capabilities, row.settings as unknown as ReconstructionSettings),
    );
    if (!candidate) return null;
    const token = randomBytes(32).toString('hex');
    const job = (
      await tx.query(
        `UPDATE reconstruction_jobs SET state='running',worker_id=$1,lease_token=$2,lease_generation=lease_generation+1,
      lease_until=clock_timestamp()+interval '90 seconds',attempts=attempts+1,stage='materializing',error_code=NULL,updated_at=clock_timestamp()
      WHERE id=$3 RETURNING *`,
        [workerId, token, candidate.id],
      )
    ).rows[0];
    await tx.query(
      `UPDATE reconstruction_capacity SET job_id=$1,worker_id=$2,lease_token=$3,lease_generation=$4,
      blocked_until=clock_timestamp()+interval '95 seconds' WHERE id=1`,
      [job.id, workerId, token, job.lease_generation],
    );
    return {
      id: String(job.id),
      restaurantId: String(job.restaurant_id),
      scanId: String(job.scan_id),
      inputHash: String(job.input_hash),
      settings: job.settings as unknown as ReconstructionSettings,
      token,
      generation: Number(job.lease_generation),
      workerId,
      attempts: Number(job.attempts),
    };
  });
}
const leaseWhere = `id=$1 AND worker_id=$2 AND lease_token=$3 AND lease_generation=$4 AND state='running' AND lease_until>clock_timestamp()`;
const leaseValues = (lease: JobLease): unknown[] => [
  lease.id,
  lease.workerId,
  lease.token,
  lease.generation,
];
const capacityWhere =
  'id=1 AND job_id=$1 AND worker_id=$2 AND lease_token=$3 AND lease_generation=$4';
async function lockOwnedCapacity(tx: Queryable, lease: JobLease): Promise<boolean> {
  const row = (await tx.query('SELECT * FROM reconstruction_capacity WHERE id=1 FOR UPDATE'))
    .rows[0];
  return (
    row?.job_id === lease.id &&
    row.worker_id === lease.workerId &&
    row.lease_token === lease.token &&
    Number(row.lease_generation) === lease.generation
  );
}
async function clearCapacity(tx: Queryable, lease: JobLease): Promise<void> {
  await tx.query(
    `UPDATE reconstruction_capacity SET job_id=NULL,worker_id=NULL,lease_token=NULL,lease_generation=NULL,blocked_until=NULL WHERE ${capacityWhere}`,
    leaseValues(lease),
  );
}
export async function renewLease(
  db: Database,
  lease: JobLease,
  stage: string | null = null,
): Promise<boolean> {
  return db.transaction(async (tx) => {
    if (!(await lockOwnedCapacity(tx, lease))) return false;
    const { rows } = await tx.query(
      `UPDATE reconstruction_jobs SET lease_until=clock_timestamp()+interval '90 seconds',stage=$5,updated_at=clock_timestamp() WHERE ${leaseWhere} RETURNING id`,
      [...leaseValues(lease), stage?.slice(0, 64) || null],
    );
    if (!rows.length) return false;
    await tx.query(
      `UPDATE reconstruction_capacity SET blocked_until=clock_timestamp()+interval '95 seconds' WHERE ${capacityWhere}`,
      leaseValues(lease),
    );
    return true;
  });
}
export async function leaseIsCurrent(db: Queryable, lease: JobLease): Promise<boolean> {
  return (
    (await db.query(`SELECT id FROM reconstruction_jobs WHERE ${leaseWhere}`, leaseValues(lease)))
      .rows.length === 1
  );
}
export async function completeJob(
  db: Database,
  lease: JobLease,
  result: Record<string, unknown>,
): Promise<boolean> {
  // Output paths/manifests remain private in result. No dishes, revisions or publications are changed here.
  return db.transaction(async (tx) => {
    if (!(await lockOwnedCapacity(tx, lease))) return false;
    const { rows } = await tx.query(
      `UPDATE reconstruction_jobs SET state='ready_for_review',result=$5,error_code=NULL,stage=NULL,
      lease_token=NULL,lease_until=NULL,worker_id=NULL,updated_at=clock_timestamp() WHERE ${leaseWhere} RETURNING id`,
      [...leaseValues(lease), JSON.stringify(result)],
    );
    if (rows.length) await clearCapacity(tx, lease);
    return rows.length === 1;
  });
}
export async function failJob(
  db: Database,
  lease: JobLease,
  code: string,
  retryable = false,
): Promise<boolean> {
  return db.transaction(async (tx) => {
    if (!(await lockOwnedCapacity(tx, lease))) return false;
    const { rows } = await tx.query(
      `UPDATE reconstruction_jobs SET state=CASE WHEN $5 AND attempts<max_attempts THEN 'queued' ELSE 'failed' END,
      error_code=$6,stage=NULL,available_at=clock_timestamp()+interval '30 seconds',lease_token=NULL,lease_until=NULL,worker_id=NULL,updated_at=clock_timestamp()
      WHERE ${leaseWhere} RETURNING id`,
      [...leaseValues(lease), retryable, code.slice(0, 80)],
    );
    if (rows.length) await clearCapacity(tx, lease);
    return rows.length === 1;
  });
}
/** Call only after the supervised process tree has exited. Cannot release another attempt's slot. */
export async function acknowledgeStopped(db: Database, lease: JobLease): Promise<boolean> {
  return db.transaction(async (tx) => {
    if (!(await lockOwnedCapacity(tx, lease))) return false;
    if (await leaseIsCurrent(tx, lease)) return false;
    await clearCapacity(tx, lease);
    return true;
  });
}
