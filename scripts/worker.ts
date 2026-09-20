/** Explicit local Linux worker. Never imported by Next.js or started by a menu request. */
import { spawn, execFile, type ChildProcess } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { createReadStream } from 'node:fs';
import {
  chmod,
  lstat,
  mkdir,
  open,
  readFile,
  readdir,
  realpath,
  stat,
  statfs,
  writeFile,
} from 'node:fs/promises';
import path from 'node:path';
import { promisify } from 'node:util';
import { Pool, type PoolClient } from 'pg';
import type { Database, Queryable, Row } from '../src/lib/server/db';
import {
  acknowledgeStopped,
  claimJob,
  completeJob,
  ENGINE_PINS,
  failJob,
  leaseIsCurrent,
  normalizeSettings,
  queueIdentity,
  renewLease,
  workerHeartbeat,
  type JobLease,
  type WorkerCapabilities,
} from '../src/lib/server/jobs';
import { ARTIFACT_PART_BYTES, storeArtifactPart } from '../src/lib/server/reconstruction-artifacts';
import { validateImageBytes } from '../src/lib/image-validation';

const exec = promisify(execFile);
const MiB = 1024 * 1024;
const project = process.cwd();
const python = process.env.WORKER_PYTHON || 'python3';
const workerId = randomUUID();
const root = path.resolve(process.env.WORKER_DATA_DIR || '.data/worker');
const workerScript = path.join(project, 'worker/reconstruct.py');
const capabilities: WorkerCapabilities = normalizeSettings({
  maxImages: Number(process.env.WORKER_MAX_IMAGES || 24),
  longEdge: Number(process.env.WORKER_LONG_EDGE || 1600),
  memoryMiB: Number(process.env.WORKER_MEMORY_MIB || 1536),
  diskMiB: Number(process.env.WORKER_DISK_MIB || 2048),
  stageSeconds: Number(process.env.WORKER_STAGE_SECONDS || 900),
  openMvsCudaBuild: process.env.WORKER_OPENMVS_CUDA_BUILD === 'true',
});
const maxJobSeconds = Number(process.env.WORKER_JOB_SECONDS || 3600);
let stopping = false;
let active: ChildProcess | null = null;
let activeStop: (() => void) | null = null;

class WorkerFailure extends Error {
  constructor(
    public code: string,
    message: string,
  ) {
    super(message);
  }
}
const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));
const digest = (bytes: Uint8Array | string) => createHash('sha256').update(bytes).digest('hex');
const safeLog = (message: string) =>
  console.log(message.replace(/postgres(?:ql)?:\/\/\S+/gi, '[database URL redacted]'));
function pythonEnvironment(): NodeJS.ProcessEnv {
  // Parsers and reconstruction engines have no reason to receive database credentials.
  const env: NodeJS.ProcessEnv = { NODE_ENV: 'production' };
  for (const key of ['PATH', 'HOME', 'LANG', 'LC_ALL', 'LD_LIBRARY_PATH', 'VIRTUAL_ENV'])
    if (process.env[key]) env[key] = process.env[key];
  return {
    ...env,
    OMP_NUM_THREADS: '1',
    OPENBLAS_NUM_THREADS: '1',
    MKL_NUM_THREADS: '1',
    NUMEXPR_NUM_THREADS: '1',
    CUDA_VISIBLE_DEVICES: '-1',
    QT_QPA_PLATFORM: 'offscreen',
    PYTHONDONTWRITEBYTECODE: '1',
  };
}

function adapter(client: Pool | PoolClient): Queryable {
  return {
    query: async <T extends Row>(sql: string, params: unknown[] = []) => ({
      rows: (await client.query<T>(sql, params)).rows,
    }),
  };
}
function databaseAdapter(pool: Pool): Database {
  return {
    ...adapter(pool),
    transaction: async <T>(fn: (db: Queryable) => Promise<T>): Promise<T> => {
      const client = await pool.connect();
      try {
        await client.query('BEGIN');
        const result = await fn(adapter(client));
        await client.query('COMMIT');
        return result;
      } catch (error) {
        await client.query('ROLLBACK');
        throw error;
      } finally {
        client.release();
      }
    },
  };
}
async function availableMiB(): Promise<number> {
  const meminfo = await readFile('/proc/meminfo', 'utf8');
  const value = Number(meminfo.match(/^MemAvailable:\s+(\d+) kB/m)?.[1]);
  if (!Number.isFinite(value))
    throw new WorkerFailure(
      'MEMORY_CHECK_UNAVAILABLE',
      'Linux memory availability could not be read.',
    );
  return value / 1024;
}
async function privateDirectory(directory: string): Promise<void> {
  await mkdir(directory, { recursive: true, mode: 0o700 });
  if ((await lstat(directory)).isSymbolicLink())
    throw new WorkerFailure('UNSAFE_DIRECTORY', 'The worker directory cannot be a symbolic link.');
  await chmod(directory, 0o700);
}
async function applyMigrations(pool: Pool): Promise<void> {
  const names = (await readdir(path.join(project, 'migrations')))
    .filter((name) => /^\d+_[a-z_]+\.sql$/.test(name))
    .sort();
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    await client.query('SELECT pg_advisory_xact_lock(73422109)');
    for (const name of names)
      await client.query(await readFile(path.join(project, 'migrations', name), 'utf8'));
    await client.query('COMMIT');
  } catch (error) {
    await client.query('ROLLBACK');
    throw error;
  } finally {
    client.release();
  }
}
async function preflight(): Promise<void> {
  if (process.env.ENABLE_RECONSTRUCTION !== 'true')
    throw new WorkerFailure(
      'NOT_ENABLED',
      'Set ENABLE_RECONSTRUCTION=true explicitly to run this worker.',
    );
  if (!process.env.DATABASE_URL)
    throw new WorkerFailure(
      'DATABASE_REQUIRED',
      'The external worker requires PostgreSQL DATABASE_URL; it never shares a PGlite data directory.',
    );
  if (process.platform !== 'linux')
    throw new WorkerFailure('LINUX_REQUIRED', 'The bounded reconstruction runner requires Linux.');
  if (!Number.isInteger(maxJobSeconds) || maxJobSeconds < 60 || maxJobSeconds > 10800)
    throw new WorkerFailure('INVALID_TIME_BUDGET', 'WORKER_JOB_SECONDS must be 60–10800.');
  // --doctor checks presence and package metadata only; it never executes the reconstruction engines.
  const { stdout } = await exec(python, [workerScript, '--doctor'], {
    cwd: project,
    timeout: 15_000,
    maxBuffer: MiB,
    encoding: 'utf8',
    env: pythonEnvironment(),
  });
  const doctor = JSON.parse(stdout) as {
    tools: Record<string, string | null>;
    pillow_installed: string | null;
    required_versions: Record<string, string>;
    run_supported_platform: boolean;
  };
  if (
    !doctor.run_supported_platform ||
    Object.values(doctor.tools).some((value) => !value) ||
    doctor.pillow_installed !== ENGINE_PINS.pillow
  ) {
    throw new WorkerFailure(
      'ENGINES_UNAVAILABLE',
      'Pinned tools/Pillow are missing. Run worker:doctor and follow docs/reconstruction.md. Nothing was installed or reconstructed.',
    );
  }
  if (Object.entries(ENGINE_PINS).some(([name, value]) => doctor.required_versions[name] !== value))
    throw new WorkerFailure(
      'ENGINE_CONFIGURATION_CHANGED',
      'The Python toolchain pins differ from the queue engine identity. Update and review both together.',
    );
  await privateDirectory(root);
}
async function fileDigest(filename: string): Promise<string> {
  const hash = createHash('sha256');
  for await (const chunk of createReadStream(filename)) hash.update(chunk);
  return hash.digest('hex');
}
async function readManifest(output: string): Promise<Record<string, unknown>> {
  const filename = path.join(output, 'manifest.json');
  const metadata = await lstat(filename);
  if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.size > MiB)
    throw new WorkerFailure(
      'INVALID_MANIFEST',
      'The output manifest is missing, unsafe or larger than 1 MiB.',
    );
  return JSON.parse(await readFile(filename, 'utf8')) as Record<string, unknown>;
}
async function materialize(db: Database, lease: JobLease, directory: string): Promise<string[]> {
  const rows = (
    await db.query(
      `SELECT f.id,f.sha256,a.id AS media_id,a.mime_type,a.byte_size FROM scan_frames f
    JOIN media_assets a ON a.id=f.media_id JOIN scan_sessions s ON s.id=f.scan_id
    WHERE s.id=$1 AND s.restaurant_id=$2 AND s.state='finalized' AND a.restaurant_id=$2 ORDER BY f.sha256`,
      [lease.scanId, lease.restaurantId],
    )
  ).rows;
  if (rows.length < 3 || rows.length > lease.settings.maxImages)
    throw new WorkerFailure(
      'FRAME_BUDGET_EXCEEDED',
      'The capture exceeds its exact image budget; no views were discarded.',
    );
  const hashes = rows.map((row) => String(row.sha256)).sort();
  const manifestHash = digest(JSON.stringify({ schema: 1, frames: hashes }));
  if (queueIdentity(manifestHash, lease.settings) !== lease.inputHash)
    throw new WorkerFailure(
      'INPUT_CHANGED',
      'Finalized capture inputs differ from the queued identity.',
    );
  let total = 0;
  for (const [index, row] of rows.entries()) {
    if (stopping || !(await leaseIsCurrent(db, lease)))
      throw new WorkerFailure('LEASE_LOST', 'The worker no longer owns this job.');
    if (!['image/jpeg', 'image/png'].includes(String(row.mime_type)))
      throw new WorkerFailure(
        'UNSUPPORTED_RECONSTRUCTION_IMAGE',
        'The engine requires JPEG or PNG inputs.',
      );
    const media = (
      await db.query('SELECT content_base64 FROM media_assets WHERE id=$1 AND restaurant_id=$2', [
        row.media_id,
        lease.restaurantId,
      ])
    ).rows[0];
    if (!media) throw new WorkerFailure('INPUT_MISSING', 'A capture original is missing.');
    const bytes = Buffer.from(String(media.content_base64), 'base64');
    validateImageBytes(bytes, String(row.mime_type));
    if (bytes.length !== Number(row.byte_size) || digest(bytes) !== row.sha256)
      throw new WorkerFailure(
        'INPUT_CHECKSUM_MISMATCH',
        'An original failed its byte-count or SHA-256 check.',
      );
    total += bytes.length;
    if (total > 120 * MiB)
      throw new WorkerFailure(
        'INPUT_BUDGET_EXCEEDED',
        'The input exceeds the 120 MiB materialization budget.',
      );
    const name = `${String(index).padStart(4, '0')}-${row.sha256}.${row.mime_type === 'image/jpeg' ? 'jpg' : 'png'}`;
    await writeFile(path.join(directory, name), bytes, { flag: 'wx', mode: 0o600 });
  }
  return hashes;
}
async function descendantMemory(pid: number): Promise<{ rssMiB: number; pids: number[] }> {
  const { stdout } = await exec('ps', ['-eo', 'pid=,ppid=,rss='], {
    encoding: 'utf8',
    maxBuffer: 4 * MiB,
    timeout: 3000,
  });
  const rows = stdout
    .trim()
    .split('\n')
    .map((line) => line.trim().split(/\s+/).map(Number));
  const descendants = new Set([pid]);
  for (let pass = 0; pass < 32; pass++)
    for (const [child, parent] of rows) if (descendants.has(parent)) descendants.add(child);
  return {
    rssMiB:
      rows.reduce((sum, [child, , rss]) => sum + (descendants.has(child) ? rss : 0), 0) / 1024,
    pids: rows.filter(([child]) => descendants.has(child)).map(([child]) => child),
  };
}
async function stopTree(child: ChildProcess): Promise<void> {
  if (!child.pid || child.exitCode !== null || child.signalCode !== null) return;
  // Python handles SIGTERM as interruption and kills its separate engine process group.
  child.kill('SIGTERM');
  await sleep(4000);
  if (child.exitCode !== null || child.signalCode !== null) return;
  // A still-running supervisor may be stuck. Signal only its currently observed descendants.
  try {
    for (const pid of (await descendantMemory(child.pid)).pids.reverse()) {
      try {
        process.kill(pid, 'SIGKILL');
      } catch {
        /* already ended */
      }
    }
  } catch {
    child.kill('SIGKILL');
  }
}
function pythonArguments(lease: JobLease, input: string, output: string): string[] {
  const settings = lease.settings;
  const args = [
    workerScript,
    '--run',
    '--supervisor-pid',
    String(process.pid),
    '--input',
    input,
    '--output',
    output,
    '--restaurant',
    lease.restaurantId,
    '--max-images',
    String(settings.maxImages),
    '--long-edge',
    String(settings.longEdge),
    '--memory-mib',
    String(settings.memoryMiB),
    '--disk-mib',
    String(settings.diskMiB),
    '--stage-seconds',
    String(settings.stageSeconds),
  ];
  if (settings.scaleMetersPerUnit !== null)
    args.push(
      '--scale-m-per-unit',
      String(settings.scaleMetersPerUnit),
      '--scale-reference',
      settings.scaleReference!,
    );
  if (settings.openMvsCudaBuild) args.push('--openmvs-cuda-build');
  return args;
}
async function verifyResult(
  lease: JobLease,
  output: string,
  hashes: string[],
): Promise<Record<string, unknown>> {
  const manifest = await readManifest(output);
  if (
    manifest.state !== 'ready_for_review' ||
    manifest.restaurant !== lease.restaurantId ||
    manifest.published !== false
  )
    throw new WorkerFailure(
      'OUTPUT_NOT_REVIEWABLE',
      'The real reconstruction has not produced an unpublished reviewable result.',
    );
  const inputs = manifest.inputs as Array<{ sha256: string }>;
  if (
    !Array.isArray(inputs) ||
    JSON.stringify(inputs.map((input) => input.sha256).sort()) !== JSON.stringify(hashes)
  )
    throw new WorkerFailure(
      'OUTPUT_INPUT_MISMATCH',
      'The output manifest is not from these capture originals.',
    );
  const outputs = manifest.outputs as Record<
    string,
    { file: string; bytes: number; sha256: string }
  >;
  const verified: Record<string, unknown> = {};
  for (const kind of ['glb', 'usdz']) {
    const item = outputs?.[kind];
    const filename = path.join(output, `model.${kind}`);
    const metadata = await lstat(filename);
    if (
      !item ||
      item.file !== `model.${kind}` ||
      !metadata.isFile() ||
      metadata.isSymbolicLink() ||
      metadata.size !== item.bytes ||
      metadata.size < 20 ||
      metadata.size > (kind === 'glb' ? 64 : 128) * MiB ||
      (await fileDigest(filename)) !== item.sha256
    ) {
      throw new WorkerFailure(
        'OUTPUT_CHECKSUM_MISMATCH',
        'A real export is absent or differs from its validated manifest.',
      );
    }
    verified[kind] = {
      bytes: item.bytes,
      sha256: item.sha256,
      parts: Math.ceil(item.bytes / ARTIFACT_PART_BYTES),
    };
  }
  const summary = {
    outputs: verified,
    elapsedSeconds: manifest.elapsed_seconds,
    requiredReviews: manifest.required_reviews,
    qualityVerified: false,
    scaleVerified: false,
    publicAssetsCreated: false,
  };
  return {
    outputDirectory: await realpath(output),
    manifest,
    summary,
    workerId,
    leaseGeneration: lease.generation,
  };
}
async function runJob(db: Database, lease: JobLease): Promise<void> {
  const jobRoot = path.join(root, `${lease.id}-${lease.generation}-${lease.token.slice(0, 12)}`);
  const input = path.join(jobRoot, 'originals');
  const output = path.join(jobRoot, 'output');
  let lostLease = false;
  let stage: string | null = 'materializing';
  let heartbeating = false;
  let guardBusy = false;
  let guardError: WorkerFailure | null = null;
  let peakMiB = 0;
  const started = Date.now();
  const stop = () => {
    if (active) void stopTree(active);
  };
  activeStop = stop;
  const heartbeat = setInterval(() => {
    if (heartbeating) return;
    heartbeating = true;
    void (async () => {
      try {
        if (
          stage !== 'materializing' &&
          stage !== 'validating_exports' &&
          stage !== 'uploading_model'
        ) {
          try {
            const manifest = await readManifest(output);
            stage = typeof manifest.active_stage === 'string' ? manifest.active_stage : stage;
          } catch {
            /* manifest is created by the running Python process */
          }
        }
        await workerHeartbeat(db, workerId, capabilities, !stopping);
        if (!(await renewLease(db, lease, stage))) {
          lostLease = true;
          stop();
        }
      } catch {
        lostLease = true;
        stop();
      } finally {
        heartbeating = false;
      }
    })();
  }, 10_000);
  const guard = setInterval(() => {
    if (guardBusy || !active?.pid || guardError) return;
    guardBusy = true;
    const child = active;
    void (async () => {
      try {
        const memory = await descendantMemory(child.pid!);
        peakMiB = Math.max(peakMiB, memory.rssMiB);
        if (memory.rssMiB > lease.settings.memoryMiB + 512 || (await availableMiB()) < 512)
          throw new WorkerFailure(
            'MEMORY_LIMIT',
            'Stopped this reconstruction to protect available laptop memory.',
          );
        if (Date.now() - started > maxJobSeconds * 1000)
          throw new WorkerFailure('JOB_TIMEOUT', 'The job exceeded its total time budget.');
      } catch (error) {
        guardError =
          error instanceof WorkerFailure
            ? error
            : new WorkerFailure(
                'RESOURCE_GUARD_UNAVAILABLE',
                'The worker could not verify its resource budget.',
              );
        stop();
      } finally {
        guardBusy = false;
      }
    })();
  }, 2000);
  try {
    await privateDirectory(jobRoot);
    await privateDirectory(input);
    const disk = await statfs(jobRoot);
    if (Number(disk.bavail) * Number(disk.bsize) < (lease.settings.diskMiB + 1024) * MiB)
      throw new WorkerFailure(
        'DISK_HEADROOM',
        'Not enough free disk space for the configured job plus 1 GiB headroom.',
      );
    const hashes = await materialize(db, lease, input);
    if (stopping || lostLease)
      throw new WorkerFailure('LEASE_LOST', 'The job was cancelled before engine startup.');
    stage = 'preflight';
    const log = await open(path.join(jobRoot, 'supervisor.log'), 'wx', 0o600);
    let exitCode: number | null;
    try {
      // No shell: every executable argument is generated from bounded settings and local paths.
      active = spawn(python, pythonArguments(lease, input, output), {
        cwd: project,
        stdio: ['ignore', log.fd, log.fd],
        detached: true,
        env: pythonEnvironment(),
      });
      exitCode = await new Promise<number | null>((resolve, reject) => {
        active!.once('error', reject);
        active!.once('exit', resolve);
      });
    } finally {
      active = null;
      await log.close();
    }
    if (lostLease)
      throw new WorkerFailure(
        'LEASE_LOST',
        'The lease expired or the job was cancelled; stale output cannot be committed.',
      );
    if (stopping) throw new WorkerFailure('WORKER_STOPPED', 'The worker was stopped.');
    if (guardError) throw guardError;
    if (exitCode !== 0)
      throw new WorkerFailure(
        'ENGINE_FAILED',
        'The reconstruction engine failed; inspect the private supervisor and stage logs.',
      );
    stage = 'validating_exports';
    const result = await verifyResult(lease, output, hashes);
    stage = 'uploading_model';
    for (const kind of ['glb', 'usdz'] as const) {
      let part = 0;
      for await (const chunk of createReadStream(path.join(output, `model.${kind}`), {
        highWaterMark: ARTIFACT_PART_BYTES,
      })) {
        if (stopping || lostLease)
          throw new WorkerFailure('LEASE_LOST', 'Model upload interrupted.');
        await storeArtifactPart(db, lease, kind, part++, chunk as Buffer);
      }
    }
    result.peakSampledProcessMiB = Math.round(peakMiB);
    if (!(await completeJob(db, lease, result)))
      throw new WorkerFailure(
        'LEASE_LOST',
        'A newer lease or cancellation prevented this completion.',
      );
    safeLog(
      `Job ${lease.id}: ready_for_review. Model returned privately to the app. Local output: ${output}. Menu publication is unchanged.`,
    );
  } catch (error) {
    const code = error instanceof WorkerFailure ? error.code : 'WORKER_FAILURE';
    try {
      await failJob(db, lease, code, code === 'WORKER_STOPPED');
    } catch {
      /* lease expiry will recover within the bounded attempt count */
    }
    safeLog(
      `Job ${lease.id}: ${code}. Originals and any previous dish model were preserved. Private logs: ${jobRoot}`,
    );
  } finally {
    clearInterval(heartbeat);
    clearInterval(guard);
    activeStop = null;
    while (heartbeating || guardBusy) await sleep(50);
    // A cancellation keeps global capacity reserved until this tree has stopped.
    try {
      await acknowledgeStopped(db, lease);
    } catch {
      /* slot quarantine expires after lease plus grace */
    }
  }
}
async function main(): Promise<void> {
  await preflight();
  const pool = new Pool({
    connectionString: process.env.DATABASE_URL,
    max: 2,
    connectionTimeoutMillis: 5000,
    idleTimeoutMillis: 20000,
    query_timeout: 10000,
  });
  const db = databaseAdapter(pool);
  try {
    await applyMigrations(pool);
    await db.query(
      "DELETE FROM reconstruction_workers WHERE last_seen_at<clock_timestamp()-interval '1 day'",
    );
    safeLog(
      `Worker ${workerId} connected. One heavy task globally; CPU only; image cap ${capabilities.maxImages}.`,
    );
    while (!stopping) {
      const ready = (await availableMiB()) >= capabilities.memoryMiB + 1024;
      await workerHeartbeat(db, workerId, capabilities, ready);
      const lease = ready ? await claimJob(db, workerId, capabilities) : null;
      if (lease) await runJob(db, lease);
      else for (let tick = 0; tick < 10 && !stopping; tick++) await sleep(500);
    }
  } finally {
    try {
      await workerHeartbeat(db, workerId, capabilities, false);
    } catch {
      /* freshness expires automatically */
    }
    await pool.end();
  }
}
for (const signal of ['SIGINT', 'SIGTERM'] as const)
  process.on(signal, () => {
    stopping = true;
    activeStop?.();
  });
main().catch((error: unknown) => {
  const message =
    error instanceof WorkerFailure
      ? `${error.code}: ${error.message}`
      : error instanceof Error
        ? error.name
        : 'UnknownError';
  safeLog(`Worker stopped: ${message}`);
  process.exitCode = 1;
});
