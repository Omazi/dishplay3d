import assert from 'node:assert/strict';
import { after, before, beforeEach, test } from 'node:test';
import { createHash, randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { PGlite } from '@electric-sql/pglite';
import type { Database, Row } from '../src/lib/server/db';
import { artifactPart, storeArtifactPart } from '../src/lib/server/reconstruction-artifacts';
import {
  requestScanReconstruction,
  scanReconstructionStatus,
} from '../src/lib/server/automatic-reconstruction';
import { ApiError } from '../src/lib/server/domain';
import {
  acknowledgeStopped,
  cancelReconstruction,
  claimJob,
  completeJob,
  enqueueReconstruction,
  failJob,
  leaseIsCurrent,
  listJobs,
  normalizeSettings,
  queueIdentity,
  renewLease,
  workerHeartbeat,
} from '../src/lib/server/jobs';

let memory: PGlite;
let db: Database;
const capabilities = normalizeSettings({
  maxImages: 40,
  memoryMiB: 2048,
  diskMiB: 4096,
  stageSeconds: 1800,
});
const hash = (text: string) => createHash('sha256').update(text).digest('hex');

before(async () => {
  memory = new PGlite();
  await memory.exec(await readFile('migrations/001_initial.sql', 'utf8'));
  await memory.exec(await readFile('migrations/002_reconstruction_queue.sql', 'utf8'));
  await memory.exec(await readFile('migrations/004_reconstruction_artifacts.sql', 'utf8'));
  await memory.exec(await readFile('migrations/005_ordered_video.sql', 'utf8'));
  db = {
    query: async <T extends Row>(sql: string, params: unknown[] = []) => ({
      rows: (await memory.query<T>(sql, params)).rows,
    }),
    transaction: (fn) =>
      memory.transaction((tx) =>
        fn({
          query: async <T extends Row>(sql: string, params: unknown[] = []) => ({
            rows: (await tx.query<T>(sql, params)).rows,
          }),
        }),
      ),
  };
});
after(async () => {
  await memory?.close();
});
beforeEach(async () => {
  await memory.exec(
    'TRUNCATE reconstruction_jobs,reconstruction_workers,scan_frames,scan_sessions,audit_events,dish_revisions,published_media,published_menu_versions,qr_links,dishes,categories,media_assets,memberships,sessions,users,restaurants CASCADE',
  );
  await memory.exec(
    'UPDATE reconstruction_capacity SET job_id=NULL,worker_id=NULL,lease_token=NULL,lease_generation=NULL,blocked_until=NULL',
  );
});

async function fixture(frameCount = 3, state = 'finalized', mime = 'image/jpeg') {
  const user = randomUUID();
  const restaurant = randomUUID();
  const dish = randomUUID();
  const scan = randomUUID();
  await db.query('INSERT INTO users(id,email,password_hash) VALUES($1,$2,$3)', [
    user,
    `${user}@example.test`,
    'test-only',
  ]);
  await db.query('INSERT INTO restaurants(id,name,slug) VALUES($1,$2,$3)', [
    restaurant,
    'Queue test',
    restaurant,
  ]);
  await db.query(
    'INSERT INTO dishes(id,restaurant_id,name,price_cents,model_glb_url) VALUES($1,$2,$3,$4,$5)',
    [dish, restaurant, 'Prior valid dish model', 1800, 'https://assets.example/previous.glb'],
  );
  const hashes = Array.from({ length: frameCount }, (_, index) =>
    hash(`state-machine-test-${index}`),
  ).sort();
  const manifestHash = hash(JSON.stringify({ schema: 1, frames: hashes }));
  await db.query(
    'INSERT INTO scan_sessions(id,restaurant_id,dish_id,state,manifest_hash) VALUES($1,$2,$3,$4,$5)',
    [scan, restaurant, dish, state, state === 'finalized' ? manifestHash : null],
  );
  // These small records test queue identity/state only; they are never processed as reconstructed photos.
  for (const sha of hashes) {
    const mediaId = randomUUID();
    await db.query(
      'INSERT INTO media_assets(id,restaurant_id,mime_type,byte_size,sha256,content_base64) VALUES($1,$2,$3,$4,$5,$6)',
      [mediaId, restaurant, mime, 1, sha, 'AA=='],
    );
    await db.query('INSERT INTO scan_frames(id,scan_id,media_id,sha256) VALUES($1,$2,$3,$4)', [
      randomUUID(),
      scan,
      mediaId,
      sha,
    ]);
  }
  return { user, restaurant, dish, scan, hashes, manifestHash };
}
async function readyWorker(id = randomUUID()) {
  await workerHeartbeat(db, id, capabilities, true);
  return id;
}

test('immutable inputs/settings deduplicate inside one restaurant only', async () => {
  const a = await fixture();
  const b = await fixture();
  await readyWorker();
  const first = await enqueueReconstruction(db, a.restaurant, a.user, a.scan);
  const repeated = await enqueueReconstruction(db, a.restaurant, a.user, a.scan, {
    longEdge: 1600,
    maxImages: 24,
  });
  assert.equal(repeated.id, first.id);
  assert.equal(repeated.deduplicated, true);
  const changedSettings = await enqueueReconstruction(db, a.restaurant, a.user, a.scan, {
    longEdge: 1200,
  });
  assert.notEqual(changedSettings.id, first.id);
  const otherRestaurant = await enqueueReconstruction(db, b.restaurant, b.user, b.scan);
  assert.notEqual(otherRestaurant.id, first.id);
  assert.notEqual(
    queueIdentity(a.manifestHash, normalizeSettings()),
    queueIdentity(a.manifestHash, normalizeSettings({ longEdge: 1200 })),
  );
});

test('jobs require owned finalized inputs, a fresh ready worker, and an explicit image budget', async () => {
  const a = await fixture();
  const open = await fixture(3, 'capturing');
  const many = await fixture(25);
  const webp = await fixture(3, 'finalized', 'image/webp');
  await assert.rejects(
    () => enqueueReconstruction(db, a.restaurant, a.user, a.scan),
    (error: unknown) => error instanceof ApiError && error.code === 'WORKER_UNAVAILABLE',
  );
  const worker = await readyWorker();
  await assert.rejects(
    () => enqueueReconstruction(db, a.restaurant, a.user, open.scan),
    (error: unknown) => error instanceof ApiError && error.status === 404,
  );
  await assert.rejects(
    () => enqueueReconstruction(db, open.restaurant, open.user, open.scan),
    (error: unknown) => error instanceof ApiError && error.code === 'SCAN_NOT_FINALIZED',
  );
  await assert.rejects(
    () => enqueueReconstruction(db, many.restaurant, many.user, many.scan),
    (error: unknown) => error instanceof ApiError && error.code === 'FRAME_BUDGET_EXCEEDED',
  );
  await assert.rejects(
    () => enqueueReconstruction(db, webp.restaurant, webp.user, webp.scan),
    (error: unknown) =>
      error instanceof ApiError && error.code === 'UNSUPPORTED_RECONSTRUCTION_IMAGE',
  );
  await db.query(
    "UPDATE reconstruction_workers SET last_seen_at=clock_timestamp()-interval '46 seconds' WHERE id=$1",
    [worker],
  );
  await assert.rejects(
    () => enqueueReconstruction(db, a.restaurant, a.user, a.scan),
    (error: unknown) => error instanceof ApiError && error.code === 'WORKER_UNAVAILABLE',
  );
});

test('single global lease, renewal, expiry reclaim and fencing prevent stale completion', async () => {
  const a = await fixture();
  const b = await fixture();
  const workerA = await readyWorker();
  const workerB = await readyWorker();
  await enqueueReconstruction(db, a.restaurant, a.user, a.scan);
  await enqueueReconstruction(db, b.restaurant, b.user, b.scan);
  const leaseA = await claimJob(db, workerA, capabilities);
  assert.ok(leaseA);
  assert.equal(await claimJob(db, workerB, capabilities), null);
  assert.equal(await renewLease(db, leaseA, 'features'), true);
  await db.query(
    "UPDATE reconstruction_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=$1",
    [leaseA.id],
  );
  assert.equal(await renewLease(db, leaseA, 'texture'), false);
  assert.equal(await claimJob(db, workerB, capabilities), null);
  await db.query(
    "UPDATE reconstruction_capacity SET blocked_until=clock_timestamp()-interval '1 second' WHERE id=1",
  );
  const leaseB = await claimJob(db, workerB, capabilities);
  assert.ok(leaseB);
  assert.equal(leaseB.id, leaseA.id);
  assert.equal(leaseB.attempts, 2);
  assert.notEqual(leaseB.token, leaseA.token);
  assert.ok(leaseB.generation > leaseA.generation);
  assert.equal(await completeJob(db, leaseA, { summary: { stale: true } }), false);
  assert.equal(await failJob(db, leaseA, 'STALE_FAILURE'), false);
  assert.equal(await acknowledgeStopped(db, leaseA), false);
  assert.equal(
    await completeJob(db, leaseB, {
      outputDirectory: '/private/review-only',
      summary: { qualityVerified: false },
    }),
    true,
  );
  assert.equal((await listJobs(db, a.restaurant))[0].state, 'ready_for_review');
  assert.equal(
    JSON.stringify(await listJobs(db, a.restaurant)).includes('/private/review-only'),
    false,
  );
  assert.equal(
    (await db.query('SELECT model_glb_url FROM dishes WHERE id=$1', [a.dish])).rows[0]
      .model_glb_url,
    'https://assets.example/previous.glb',
  );
});

test('owner cancellation fences running work and preserves captures and prior model', async () => {
  const a = await fixture();
  const b = await fixture();
  const worker = await readyWorker();
  const created = await enqueueReconstruction(db, a.restaurant, a.user, a.scan);
  const lease = await claimJob(db, worker, capabilities);
  assert.ok(lease);
  await assert.rejects(
    () => cancelReconstruction(db, b.restaurant, created.id),
    (error: unknown) => error instanceof ApiError && error.status === 404,
  );
  assert.equal((await cancelReconstruction(db, a.restaurant, created.id)).state, 'cancelled');
  assert.equal((await cancelReconstruction(db, a.restaurant, created.id)).state, 'cancelled');
  assert.equal(await leaseIsCurrent(db, lease), false);
  assert.equal(await renewLease(db, lease), false);
  assert.equal(await completeJob(db, lease, { summary: {} }), false);
  assert.equal(
    (
      await db.query('SELECT count(*)::integer AS count FROM scan_frames WHERE scan_id=$1', [
        a.scan,
      ])
    ).rows[0].count,
    3,
  );
  assert.equal(
    (await db.query('SELECT model_glb_url FROM dishes WHERE id=$1', [a.dish])).rows[0]
      .model_glb_url,
    'https://assets.example/previous.glb',
  );
  await enqueueReconstruction(db, b.restaurant, b.user, b.scan);
  assert.equal(
    await claimJob(db, worker, capabilities),
    null,
    'Cancelled job keeps capacity until its process stops',
  );
  assert.equal(await acknowledgeStopped(db, lease), true);
  assert.ok(await claimJob(db, worker, capabilities));
});

test('expired leases and retryable failures stop after two attempts', async () => {
  const a = await fixture();
  const worker = await readyWorker();
  const created = await enqueueReconstruction(db, a.restaurant, a.user, a.scan);
  const first = await claimJob(db, worker, capabilities);
  assert.ok(first);
  assert.equal(await failJob(db, first, 'WORKER_STOPPED', true), true);
  assert.equal(await claimJob(db, worker, capabilities), null);
  await db.query(
    "UPDATE reconstruction_jobs SET available_at=clock_timestamp()-interval '1 second' WHERE id=$1",
    [created.id],
  );
  const second = await claimJob(db, worker, capabilities);
  assert.ok(second);
  assert.equal(second.attempts, 2);
  await db.query(
    "UPDATE reconstruction_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=$1",
    [created.id],
  );
  await db.query(
    "UPDATE reconstruction_capacity SET blocked_until=clock_timestamp()-interval '1 second' WHERE id=1",
  );
  assert.equal(await claimJob(db, worker, capabilities), null);
  assert.equal((await listJobs(db, a.restaurant))[0].state, 'failed');
  assert.equal((await listJobs(db, a.restaurant))[0].errorCode, 'LEASE_EXPIRED');
});

test('automatic reconstruction queues offline, deduplicates and reports actual PC availability', async () => {
  const priorEnabled = process.env.ENABLE_RECONSTRUCTION,
    priorDb = process.env.DATABASE_URL;
  process.env.ENABLE_RECONSTRUCTION = 'true';
  process.env.DATABASE_URL = 'test-only';
  try {
    const a = await fixture();
    const request = () =>
      db.transaction((tx) => requestScanReconstruction(tx, a.restaurant, a.user, a.scan));
    const first = await request();
    assert.equal(first.state, 'queued');
    assert.deepEqual(
      (await scanReconstructionStatus(db, a.restaurant, a.scan)).workerAvailable,
      false,
    );
    const again = await request();
    assert.ok('id' in first && 'id' in again && first.id === again.id);
    const worker = await readyWorker();
    const lease = await claimJob(db, worker, capabilities);
    assert.ok(lease);
    assert.equal((await scanReconstructionStatus(db, a.restaurant, a.scan)).job?.state, 'running');
    assert.equal((await scanReconstructionStatus(db, randomUUID(), a.scan)).job, null);
  } finally {
    if (priorEnabled === undefined) delete process.env.ENABLE_RECONSTRUCTION;
    else process.env.ENABLE_RECONSTRUCTION = priorEnabled;
    if (priorDb === undefined) delete process.env.DATABASE_URL;
    else process.env.DATABASE_URL = priorDb;
  }
});

test('model parts are private until fenced completion and inaccessible to other dishes or tenants', async () => {
  const a = await fixture(),
    b = await fixture();
  const worker = await readyWorker();
  const queued = await enqueueReconstruction(db, a.restaurant, a.user, a.scan);
  const lease = (await claimJob(db, worker, capabilities))!;
  const bytes = Buffer.from('artifact transport fixture; not reconstruction evidence');
  await storeArtifactPart(db, lease, 'glb', 0, bytes);
  await assert.rejects(
    () => artifactPart(db, a.restaurant, queued.id, 'glb', '0'),
    (err: unknown) => err instanceof ApiError && err.status === 404,
  );
  assert.equal(
    await completeJob(db, lease, {
      leaseGeneration: lease.generation,
      summary: {
        outputs: { glb: { bytes: bytes.length, sha256: hash(bytes.toString()), parts: 1 } },
      },
    }),
    true,
  );
  const response = await artifactPart(db, a.restaurant, queued.id, 'glb', '0', a.scan);
  assert.deepEqual(Buffer.from(await response.arrayBuffer()), bytes);
  assert.equal(response.headers.get('X-Artifact-SHA256'), hash(bytes.toString()));
  assert.equal(response.headers.get('Cache-Control'), 'private, no-store');
  for (const [restaurant, scan] of [
    [b.restaurant, b.scan],
    [a.restaurant, b.scan],
  ]) {
    await assert.rejects(
      () => artifactPart(db, restaurant, queued.id, 'glb', '0', scan),
      (err: unknown) => err instanceof ApiError && err.status === 404,
    );
  }
  await assert.rejects(() => artifactPart(db, a.restaurant, queued.id, 'glb', '1'));
  await assert.rejects(() => artifactPart(db, a.restaurant, queued.id, '../secret', '0'));
  await assert.rejects(() => storeArtifactPart(db, lease, 'glb', 1, bytes), /lease expired/);
});

test('raw-video jobs preserve leases and cannot be claimed by a legacy worker', async () => {
  const { attachVideo } = await import('../src/lib/server/capture-video');
  const { finalizeScan } = await import('../src/lib/server/scans');
  const { ORDERED_RECONSTRUCTION_ENGINE } = await import('../src/lib/server/jobs');
  const f = await fixture(0, 'capturing');
  await db.transaction((tx) =>
    attachVideo(
      tx,
      f.scan,
      f.restaurant,
      { backend: 'local-v1', key: randomUUID() + '.video', sha256: hash('video'), bytes: 100 },
      'video/mp4',
    ),
  );
  const finalized = await db.transaction((tx) => finalizeScan(tx, f.scan, f.restaurant, f.user));
  assert.equal(finalized.manifestSchema, 2);
  const queued = await enqueueReconstruction(db, f.restaurant, f.user, f.scan, {}, true);
  assert.equal(
    (await db.query('SELECT engine FROM reconstruction_jobs WHERE id=$1', [queued.id])).rows[0]
      .engine,
    ORDERED_RECONSTRUCTION_ENGINE,
  );
  const oldWorker = await readyWorker();
  assert.equal(await claimJob(db, oldWorker, capabilities), null);
  const worker = randomUUID(),
    videoCapabilities = { ...capabilities, orderedCapture: true, rawVideo: true };
  await workerHeartbeat(db, worker, videoCapabilities, true);
  const lease = await claimJob(db, worker, videoCapabilities);
  assert.equal(lease?.id, queued.id);
  assert.equal(await renewLease(db, lease!, 'video_decode'), true);
  assert.equal(await failJob(db, lease!, 'VIDEO_DECODE_FAILED'), true);
  assert.equal((await listJobs(db, f.restaurant))[0].errorCode, 'VIDEO_DECODE_FAILED');
});
test('frozen raw video mutation invalidates admission identity', async () => {
  const { attachVideo } = await import('../src/lib/server/capture-video');
  const { finalizeScan } = await import('../src/lib/server/scans');
  const f = await fixture(0, 'capturing');
  await db.transaction((tx) =>
    attachVideo(
      tx,
      f.scan,
      f.restaurant,
      { backend: 'local-v1', key: randomUUID() + '.video', sha256: hash('video'), bytes: 100 },
      'video/mp4',
    ),
  );
  await db.transaction((tx) => finalizeScan(tx, f.scan, f.restaurant, f.user));
  await db.query('UPDATE capture_videos SET sha256=$1 WHERE scan_id=$2', [hash('changed'), f.scan]);
  await assert.rejects(
    () => enqueueReconstruction(db, f.restaurant, f.user, f.scan, {}, true),
    (e: unknown) => e instanceof ApiError && e.code === 'INPUT_CHANGED',
  );
});
