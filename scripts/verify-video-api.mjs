// HTTP-only integration smoke. Uses a fresh disposable database; never production credentials.
import assert from 'node:assert/strict';
import { spawn, execFileSync } from 'node:child_process';
import { createHash, randomBytes, randomUUID } from 'node:crypto';
import { mkdtemp, readFile, rm, open } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';

const root = await mkdtemp(path.join(tmpdir(), 'dishplay-video-http-'));
const port = 3119;
const base = `http://127.0.0.1:${port}`;
const log = await open(path.join(root, 'server.log'), 'w');
const server = spawn(
  process.execPath,
  [
    '--max-old-space-size=512',
    'node_modules/next/dist/bin/next',
    'start',
    '--hostname',
    '127.0.0.1',
    '--port',
    String(port),
  ],
  {
    env: {
      ...process.env,
      DATABASE_URL: '',
      VERCEL: '',
      ENABLE_RECONSTRUCTION: 'false',
      ALLOW_LOCAL_DATABASE: 'true',
      ALLOW_SIGNUP: 'true',
      PGLITE_DATA_DIR: path.join(root, 'db'),
      CAPTURE_VIDEO_DIR: path.join(root, 'videos'),
      NEXT_PUBLIC_APP_URL: base,
      MEDIA_PUBLIC_ORIGIN: 'https://assets.example.test',
    },
    stdio: ['ignore', log.fd, log.fd],
  },
);
const exit = new Promise((resolve) => server.once('exit', resolve));
let cookie = '';
const hash = (bytes) => createHash('sha256').update(bytes).digest('hex');
async function call(route, body, headers = {}, expected = 200, authenticated = true) {
  const binary = Buffer.isBuffer(body);
  const response = await fetch(base + route, {
    method: body === undefined ? 'GET' : 'POST',
    headers: {
      ...(authenticated ? { Cookie: cookie, Origin: base } : {}),
      ...(body !== undefined && !binary ? { 'Content-Type': 'application/json' } : {}),
      ...headers,
    },
    ...(body === undefined ? {} : { body: binary ? body : JSON.stringify(body) }),
  });
  const text = await response.text();
  assert.equal(response.status, expected, `${route}: ${text}`);
  return { body: JSON.parse(text), cookie: response.headers.get('set-cookie')?.split(';')[0] };
}
try {
  let started = false;
  for (let attempt = 0; attempt < 60; attempt++) {
    if (server.exitCode !== null) throw new Error('Isolated test server failed to start');
    try {
      if ((await fetch(base + '/api/health')).ok) {
        started = true;
        break;
      }
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  assert.ok(started, 'Test server startup timeout');
  const signup = await call(
    '/api/auth/signup',
    {
      email: `video-${randomUUID()}@example.test`,
      password: `DishPlay-${randomUUID()}`,
      restaurantName: 'Isolated video API test',
    },
    {},
    201,
  );
  cookie = signup.cookie;
  const {
    body: { dish },
  } = await call('/api/dishes', { name: 'Video fixture', priceCents: 1000 }, {}, 201);
  const newScan = async () =>
    (
      await call(
        '/api/scans',
        {
          dishId: dish.id,
          sourceType: 'video',
          captureMetadata: { lens: 'wide', intrinsics: { fx: 1000, fy: 1000 } },
        },
        {},
        201,
      )
    ).body.scan;
  const ordered = await newScan();
  const image = await readFile('public/images/burger.jpg');
  const frameHeaders = (index) => ({
    'Content-Type': 'image/jpeg',
    'X-Content-SHA256': hash(image),
    'X-Frame-Metadata': JSON.stringify({
      frameIndex: index,
      timestampMs: index * 250,
      lens: 'wide',
    }),
  });
  for (const index of [2, 0, 1])
    await call(`/api/scans/${ordered.id}/frames`, image, frameHeaders(index), 201);
  await call(`/api/scans/${ordered.id}/frames`, image, frameHeaders(1), 200);
  await call(
    `/api/scans/${ordered.id}/frames`,
    image,
    { ...frameHeaders(1), 'X-Frame-Metadata': '{"frameIndex":1,"timestampMs":300}' },
    409,
  );
  const finalized = (await call(`/api/scans/${ordered.id}/finalize`, {})).body.scan;
  assert.equal(finalized.manifestSchema, 2);
  const retrieved = (await call(`/api/scans/${ordered.id}`)).body;
  assert.deepEqual(
    retrieved.frames.map((frame) => frame.frameIndex),
    [0, 1, 2],
  );
  assert.deepEqual(
    retrieved.frames.map((frame) => frame.timestampMs),
    [0, 250, 500],
  );
  await call(`/api/scans/${ordered.id}/frames`, image, frameHeaders(3), 409);
  const videoPath = path.join(root, 'fixture.mp4');
  execFileSync(
    'ffmpeg',
    [
      '-nostdin',
      '-v',
      'error',
      '-f',
      'lavfi',
      '-i',
      'testsrc2=size=320x240:rate=5:duration=1',
      '-c:v',
      'libx264',
      '-threads',
      '1',
      '-pix_fmt',
      'yuv420p',
      videoPath,
    ],
    { timeout: 15000 },
  );
  const video = await readFile(videoPath);
  const videoHeaders = { 'Content-Type': 'video/mp4', 'X-Content-SHA256': hash(video) };
  const raw = await newScan();
  await call(`/api/scans/${raw.id}/video`, video, { ...videoHeaders, Origin: base }, 401, false);
  await call(
    `/api/scans/${raw.id}/video`,
    video,
    { ...videoHeaders, 'X-Content-SHA256': '0'.repeat(64) },
    400,
  );
  const receipt = await call(`/api/scans/${raw.id}/video`, video, videoHeaders, 201);
  assert.equal(receipt.body.validation, 'pending_worker_decode');
  assert.equal(
    (await call(`/api/scans/${raw.id}/video`, video, videoHeaders)).body.duplicate,
    true,
  );
  await call(`/api/scans/${raw.id}/frames`, image, frameHeaders(0), 409);
  assert.equal((await call(`/api/scans/${raw.id}/finalize`, {})).body.scan.state, 'finalized');
  await call(`/api/scans/${raw.id}/video`, video, videoHeaders, 409);
  const link = (await call('/api/capture-links', { dishId: dish.id }, {}, 201)).body;
  const secret = randomBytes(32).toString('hex');
  await call('/api/native/pair', { code: link.code, deviceSecret: secret }, {}, 200, false);
  await call('/api/native/video', video, videoHeaders, 401, false);
  await call(
    '/api/native/video',
    video,
    { ...videoHeaders, Authorization: `Bearer ${secret}` },
    201,
    false,
  );
  await call('/api/native/finalize', {}, { Authorization: `Bearer ${secret}` }, 200, false);
  console.log(
    'PASS: ordered frame upload/retry/conflict/order/finalization; raw video hash/auth/deduplication/mixed-source/immutability; native video pairing/upload/finalization.',
  );
} catch (error) {
  console.error(await readFile(path.join(root, 'server.log'), 'utf8'));
  throw error;
} finally {
  server.kill('SIGTERM');
  const force = setTimeout(() => server.kill('SIGKILL'), 3000);
  await exit;
  clearTimeout(force);
  await log.close();
  await rm(root, { recursive: true, force: true });
}
