import { randomBytes } from 'node:crypto';
import { digest, newId, type Identity } from './auth';
import { lockRestaurant, audit } from './catalogue';
import { type Database, type Queryable, type Row } from './db';
import { ApiError, MAX_IMAGE_BYTES } from './domain';
import { scanFrames, ownedScan, scanFromRow } from './scans';

const denied = () =>
  new ApiError(
    401,
    'This capture access has expired or was revoked. Create a new association from your restaurant account.',
    'CAPTURE_ACCESS_DENIED',
  );
export async function issueCaptureLink(db: Database, identity: Identity, dishId: string) {
  return db.transaction(async (tx) => {
    await lockRestaurant(tx, identity.restaurantId);
    const dish = (
      await tx.query('SELECT id FROM dishes WHERE id=$1 AND restaurant_id=$2', [
        dishId,
        identity.restaurantId,
      ])
    ).rows[0];
    if (!dish) throw new ApiError(404, 'Dish not found.', 'NOT_FOUND');
    await tx.query(
      'UPDATE native_capture_links SET revoked_at=now() WHERE restaurant_id=$1 AND dish_id=$2 AND claimed_at IS NULL AND revoked_at IS NULL',
      [identity.restaurantId, dishId],
    );
    const code = randomBytes(8).toString('hex').toUpperCase();
    const expiresAt = new Date(Date.now() + 10 * 60_000).toISOString();
    const id = newId();
    await tx.query(
      'INSERT INTO native_capture_links(id,restaurant_id,dish_id,created_by,code_hash,code_expires_at) VALUES($1,$2,$3,$4,$5,$6)',
      [id, identity.restaurantId, dishId, identity.user.id, digest(code), expiresAt],
    );
    await audit(tx, identity.restaurantId, identity.user.id, 'capture.link.created', {
      linkId: id,
      dishId,
    });
    return { id, code: code.match(/.{4}/g)!.join('-'), expiresAt };
  });
}
export async function limitPairing(db: Queryable, ip: string) {
  const { rows } = await db.query(
    `INSERT INTO rate_limits(key,attempts) VALUES($1,1)
    ON CONFLICT(key) DO UPDATE SET attempts=CASE WHEN rate_limits.window_start < now()-interval '15 minutes' THEN 1 ELSE rate_limits.attempts+1 END,
    window_start=CASE WHEN rate_limits.window_start < now()-interval '15 minutes' THEN now() ELSE rate_limits.window_start END RETURNING attempts`,
    [digest('native-pair:' + ip)],
  );
  if (Number(rows[0].attempts) > 20)
    throw new ApiError(
      429,
      'Too many association attempts. Try again in 15 minutes.',
      'RATE_LIMITED',
    );
}
export async function captureSnapshot(tx: Queryable, grant: Row) {
  const scan = await ownedScan(tx, String(grant.scan_id), String(grant.restaurant_id));
  const frames = await scanFrames(tx, String(scan.id));
  const names = (
    await tx.query(
      'SELECT d.name AS dish_name,r.name AS restaurant_name FROM dishes d JOIN restaurants r ON r.id=d.restaurant_id WHERE d.id=$1',
      [grant.dish_id],
    )
  ).rows[0];
  return {
    scan: { ...scanFromRow(scan), frameCount: frames.length },
    dishName: String(names.dish_name),
    restaurantName: String(names.restaurant_name),
    expiresAt: new Date(String(grant.token_expires_at)).toISOString(),
    hashes: frames.map((f) => f.sha256),
    limits: { maxImageBytes: MAX_IMAGE_BYTES, maxFrames: 150 },
  };
}
export async function claimCaptureLink(db: Database, rawCode: unknown, secret: unknown) {
  const code = typeof rawCode === 'string' ? rawCode.replace(/[\s-]/g, '').toUpperCase() : '';
  if (!/^[A-F0-9]{16}$/.test(code) || typeof secret !== 'string' || !/^[a-f0-9]{64}$/.test(secret))
    throw new ApiError(400, 'Enter a valid association code.', 'INVALID_PAIRING');
  const found = (
    await db.query('SELECT restaurant_id,id FROM native_capture_links WHERE code_hash=$1', [
      digest(code),
    ])
  ).rows[0];
  if (!found) throw denied();
  return db.transaction(async (tx) => {
    await lockRestaurant(tx, String(found.restaurant_id));
    let grant = (
      await tx.query('SELECT * FROM native_capture_links WHERE id=$1 FOR UPDATE', [found.id])
    ).rows[0];
    if (!grant || grant.revoked_at) throw denied();
    if (grant.claimed_at) {
      if (grant.token_hash !== digest(secret))
        throw new ApiError(409, 'This code was already used. Create a new code.', 'CODE_USED');
      if (new Date(String(grant.token_expires_at)).getTime() <= Date.now()) throw denied();
      return captureSnapshot(tx, grant);
    }
    if (new Date(String(grant.code_expires_at)).getTime() <= Date.now()) throw denied();
    const active = (
      await tx.query(
        "SELECT count(*)::integer AS count FROM scan_sessions WHERE restaurant_id=$1 AND state='capturing'",
        [grant.restaurant_id],
      )
    ).rows[0];
    if (Number(active.count) >= 10)
      throw new ApiError(400, 'Finish or cancel an existing capture before creating another.');
    const scanId = newId();
    await tx.query('INSERT INTO scan_sessions(id,restaurant_id,dish_id) VALUES($1,$2,$3)', [
      scanId,
      grant.restaurant_id,
      grant.dish_id,
    ]);
    grant = (
      await tx.query(
        "UPDATE native_capture_links SET token_hash=$1,token_expires_at=now()+interval '7 days',scan_id=$2,claimed_at=now() WHERE id=$3 RETURNING *",
        [digest(secret), scanId, grant.id],
      )
    ).rows[0];
    await audit(tx, String(grant.restaurant_id), String(grant.created_by), 'capture.link.claimed', {
      linkId: grant.id,
      scanId,
    });
    return captureSnapshot(tx, grant);
  });
}
// Recheck credentials under the same restaurant lock as revocation and scan writes.
export async function withNativeCapture<T>(
  db: Database,
  authorization: string | null,
  work: (tx: Queryable, grant: Row) => Promise<T>,
): Promise<T> {
  const secret = /^Bearer ([a-f0-9]{64})$/.exec(authorization || '')?.[1];
  if (!secret) throw denied();
  const found = (
    await db.query('SELECT restaurant_id,id FROM native_capture_links WHERE token_hash=$1', [
      digest(secret),
    ])
  ).rows[0];
  if (!found) throw denied();
  return db.transaction(async (tx) => {
    await lockRestaurant(tx, String(found.restaurant_id));
    const grant = (
      await tx.query('SELECT * FROM native_capture_links WHERE id=$1 FOR UPDATE', [found.id])
    ).rows[0];
    if (
      !grant ||
      grant.revoked_at ||
      !grant.scan_id ||
      new Date(String(grant.token_expires_at)).getTime() <= Date.now()
    )
      throw denied();
    return work(tx, grant);
  });
}
