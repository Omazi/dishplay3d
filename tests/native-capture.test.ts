import assert from 'node:assert/strict';
import { after, before, beforeEach, test } from 'node:test';
import { randomBytes, randomUUID } from 'node:crypto';
import { readFile, readdir } from 'node:fs/promises';
import { PGlite } from '@electric-sql/pglite';
import { NextRequest, NextResponse } from 'next/server';
import type { Database, Row } from '../src/lib/server/db';
import { ApiError } from '../src/lib/server/domain';
import {
  issueCaptureLink,
  claimCaptureLink,
  withNativeCapture,
  captureSnapshot,
  limitPairing,
} from '../src/lib/server/native-capture';
import { appendScanFrame, finalizeScan } from '../src/lib/server/scans';
import { api } from '../src/lib/server/http';

let memory: PGlite;
let db: Database;
before(async () => {
  memory = new PGlite();
  for (const file of (await readdir('migrations')).filter((f) => f.endsWith('.sql')).sort())
    await memory.exec(await readFile(`migrations/${file}`, 'utf8'));
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
  await memory.exec('TRUNCATE users,restaurants,rate_limits CASCADE');
});
async function fixture() {
  const user = { id: randomUUID(), email: randomUUID() + '@example.test' };
  const restaurantId = randomUUID(),
    dishId = randomUUID();
  await db.query('INSERT INTO users(id,email,password_hash) VALUES($1,$2,$3)', [
    user.id,
    user.email,
    'fixture',
  ]);
  await db.query('INSERT INTO restaurants(id,name,slug) VALUES($1,$2,$3)', [
    restaurantId,
    'Fixture restaurant',
    restaurantId,
  ]);
  await db.query('INSERT INTO dishes(id,restaurant_id,name,price_cents) VALUES($1,$2,$3,$4)', [
    dishId,
    restaurantId,
    'Fixture dish',
    1000,
  ]);
  return { identity: { user, restaurantId }, dishId };
}
const secret = () => randomBytes(32).toString('hex');
const status = (expected: number) => (error: unknown) =>
  error instanceof ApiError && error.status === expected;

test('pairing is owner-scoped and idempotent after a lost response, with no plaintext secrets stored', async () => {
  const a = await fixture(),
    b = await fixture();
  await assert.rejects(() => issueCaptureLink(db, b.identity, a.dishId), status(404));
  const link = await issueCaptureLink(db, a.identity, a.dishId),
    token = secret();
  const first = await claimCaptureLink(db, link.code, token);
  await db.query(
    "UPDATE native_capture_links SET code_expires_at=now()-interval '1 minute' WHERE id=$1",
    [link.id],
  );
  const retry = await claimCaptureLink(db, link.code, token);
  assert.equal(retry.scan.id, first.scan.id);
  assert.equal(retry.expiresAt, first.expiresAt, 'retries cannot extend capability lifetime');
  await assert.rejects(() => claimCaptureLink(db, link.code, secret()), status(409));
  assert.equal((await db.query('SELECT count(*)::integer AS n FROM scan_sessions')).rows[0].n, 1);
  const stored = JSON.stringify((await db.query('SELECT * FROM native_capture_links')).rows);
  assert.ok(!stored.includes(token));
  assert.ok(!stored.includes(link.code.replaceAll('-', '')));
  assert.equal(first.dishName, 'Fixture dish');
});

test('replacement codes invalidate only unclaimed codes; expired or revoked credentials stop immediately', async () => {
  const a = await fixture();
  const old = await issueCaptureLink(db, a.identity, a.dishId);
  const current = await issueCaptureLink(db, a.identity, a.dishId);
  await assert.rejects(() => claimCaptureLink(db, old.code, secret()), status(401));
  const token = secret();
  await claimCaptureLink(db, current.code, token);
  await issueCaptureLink(db, a.identity, a.dishId);
  assert.equal(
    (await withNativeCapture(db, 'Bearer ' + token, captureSnapshot)).scan.frameCount,
    0,
  );
  await db.query(
    "UPDATE native_capture_links SET token_expires_at=now()-interval '1 second' WHERE id=$1",
    [current.id],
  );
  await assert.rejects(
    () => withNativeCapture(db, 'Bearer ' + token, captureSnapshot),
    status(401),
  );
  const fresh = await issueCaptureLink(db, a.identity, a.dishId);
  await db.query(
    "UPDATE native_capture_links SET code_expires_at=now()-interval '1 second' WHERE id=$1",
    [fresh.id],
  );
  await assert.rejects(() => claimCaptureLink(db, fresh.code, secret()), status(401));
});

test('concurrent claims create one scan and never let a second secret take it over', async () => {
  const a = await fixture(),
    link = await issueCaptureLink(db, a.identity, a.dishId);
  const tokens = [secret(), secret()];
  const results = await Promise.allSettled(
    tokens.map((token) => claimCaptureLink(db, link.code, token)),
  );
  assert.equal(results.filter((r) => r.status === 'fulfilled').length, 1);
  assert.equal((await db.query('SELECT count(*)::integer AS n FROM scan_sessions')).rows[0].n, 1);
});

test('resumable native uploads share deduplication, finalization and immutability with browser captures', async () => {
  const a = await fixture(),
    link = await issueCaptureLink(db, a.identity, a.dishId),
    token = secret();
  const claimed = await claimCaptureLink(db, link.code, token);
  const write = (bytes: Uint8Array) =>
    withNativeCapture(db, 'Bearer ' + token, (tx, g) =>
      appendScanFrame(tx, String(g.scan_id), String(g.restaurant_id), bytes, 'image/jpeg'),
    );
  const finish = () =>
    withNativeCapture(db, 'Bearer ' + token, (tx, g) =>
      finalizeScan(tx, String(g.scan_id), String(g.restaurant_id), String(g.created_by)),
    );
  const bytes = await readFile('public/images/burger.jpg');
  assert.equal((await write(bytes)).duplicate, false);
  assert.equal((await write(bytes)).duplicate, true);
  await assert.rejects(finish, status(400));
  await write(await readFile('public/images/pasta.jpg'));
  await write(await readFile('public/images/salad.jpg'));
  const result = await finish();
  assert.equal(result.frameCount, 3);
  assert.equal(result.state, 'finalized');
  assert.deepEqual(await finish(), result);
  await assert.rejects(() => write(bytes), status(409));
  await db.query('UPDATE native_capture_links SET revoked_at=now() WHERE id=$1', [link.id]);
  await assert.rejects(
    () => withNativeCapture(db, 'Bearer ' + token, captureSnapshot),
    status(401),
  );
  assert.equal(
    (
      await db.query('SELECT count(*)::integer AS n FROM scan_frames WHERE scan_id=$1', [
        claimed.scan.id,
      ])
    ).rows[0].n,
    3,
  );
});

test('active capture quota and pairing rate limit remain enforced', async () => {
  const a = await fixture();
  for (let i = 0; i < 10; i++)
    await db.query('INSERT INTO scan_sessions(id,restaurant_id,dish_id) VALUES($1,$2,$3)', [
      randomUUID(),
      a.identity.restaurantId,
      a.dishId,
    ]);
  const link = await issueCaptureLink(db, a.identity, a.dishId);
  await assert.rejects(() => claimCaptureLink(db, link.code, secret()), status(400));
  for (let i = 0; i < 20; i++) await limitPairing(db, '192.0.2.61');
  await assert.rejects(() => limitPairing(db, '192.0.2.61'), status(429));
  await limitPairing(db, '192.0.2.62');
});

test('missing Origin is allowed only on native-capability routes, foreign origins stay rejected', async () => {
  const browser = api(async () => NextResponse.json({ ok: true }));
  const native = api(async () => NextResponse.json({ ok: true }), { nativeCapability: true });
  const request = (headers: Record<string, string> = {}) =>
    new NextRequest('http://localhost:3000/api/native/pair', { method: 'POST', headers });
  assert.equal((await browser(request())).status, 403);
  assert.equal((await native(request())).status, 200);
  assert.equal((await native(request({ Origin: 'https://foreign.example' }))).status, 403);
  assert.equal((await browser(request({ Origin: 'http://localhost:3000' }))).status, 200);
  await assert.rejects(() => withNativeCapture(db, null, captureSnapshot), status(401));
});
