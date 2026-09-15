import { createHash, randomBytes, randomUUID, scrypt, timingSafeEqual } from 'node:crypto';
import { promisify } from 'node:util';
import { NextRequest, NextResponse } from 'next/server';
import { database, type Queryable, type Row } from './db';
import { ApiError } from './domain';

const scryptAsync = promisify(scrypt);
export const SESSION_COOKIE = 'dishplay_session';
export const secureCookie = (): boolean =>
  Boolean(process.env.VERCEL) ||
  (process.env.NODE_ENV === 'production' && process.env.ALLOW_LOCAL_DATABASE !== 'true');
const SESSION_SECONDS = 7 * 24 * 60 * 60;
export const digest = (value: string | Uint8Array): string =>
  createHash('sha256').update(value).digest('hex');
export const newId = (): string => randomUUID();

export async function hashPassword(password: string): Promise<string> {
  const salt = randomBytes(16).toString('hex');
  const derived = (await scryptAsync(password, salt, 64)) as Buffer;
  return `scrypt:${salt}:${derived.toString('hex')}`;
}
export async function verifyPassword(password: string, hash: string): Promise<boolean> {
  const [algorithm, salt, stored] = hash.split(':');
  if (algorithm !== 'scrypt' || !salt || !stored || !/^[0-9a-f]{128}$/.test(stored)) return false;
  const derived = (await scryptAsync(password, salt, 64)) as Buffer;
  return timingSafeEqual(derived, Buffer.from(stored, 'hex'));
}
export interface Identity {
  user: { id: string; email: string };
  restaurantId: string;
}
export async function currentUser(request: NextRequest): Promise<Identity | null> {
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (!token || !/^[a-f0-9]{64}$/.test(token)) return null;
  const db = await database();
  const { rows } = await db.query<Row>(
    `SELECT u.id, u.email, m.restaurant_id FROM sessions s
    JOIN users u ON u.id=s.user_id JOIN memberships m ON m.user_id=u.id
    WHERE s.token_hash=$1 AND s.expires_at>now() ORDER BY m.restaurant_id LIMIT 1`,
    [digest(token)],
  );
  if (!rows[0]) return null;
  return {
    user: { id: String(rows[0].id), email: String(rows[0].email) },
    restaurantId: String(rows[0].restaurant_id),
  };
}
export async function requireUser(request: NextRequest): Promise<Identity> {
  const identity = await currentUser(request);
  if (!identity) throw new ApiError(401, 'Sign in to continue.', 'UNAUTHENTICATED');
  return identity;
}
export async function createSession(db: Queryable, userId: string): Promise<string> {
  const token = randomBytes(32).toString('hex');
  await db.query('INSERT INTO sessions(token_hash,user_id,expires_at) VALUES($1,$2,$3)', [
    digest(token),
    userId,
    new Date(Date.now() + SESSION_SECONDS * 1000),
  ]);
  await db.query('DELETE FROM sessions WHERE expires_at < now()');
  return token;
}
export function setSession(response: NextResponse, token: string): NextResponse {
  response.cookies.set(SESSION_COOKIE, token, {
    httpOnly: true,
    secure: secureCookie(),
    sameSite: 'lax',
    path: '/',
    maxAge: SESSION_SECONDS,
  });
  return response;
}
export async function limitAuth(
  request: NextRequest,
  email: string,
  action: 'login' | 'signup',
): Promise<void> {
  const ip = request.headers.get('x-forwarded-for')?.split(',')[0]?.trim() || 'local';
  const key = digest(`${action}:${ip}:${action === 'login' ? email : ''}`);
  const db = await database();
  await db.query("DELETE FROM rate_limits WHERE window_start < now()-interval '1 day'");
  if (action === 'login') {
    const ipKey = digest(`ip-login:${ip}`);
    const ipLimit = await db.query(
      `INSERT INTO rate_limits(key,attempts) VALUES($1,1)
      ON CONFLICT(key) DO UPDATE SET attempts=CASE WHEN rate_limits.window_start < now()-interval '15 minutes' THEN 1 ELSE rate_limits.attempts+1 END,
      window_start=CASE WHEN rate_limits.window_start < now()-interval '15 minutes' THEN now() ELSE rate_limits.window_start END RETURNING attempts`,
      [ipKey],
    );
    if (Number(ipLimit.rows[0]?.attempts) > 50)
      throw new ApiError(429, 'Too many attempts. Try again in 15 minutes.', 'RATE_LIMITED');
  }
  const { rows } = await db.query(
    `INSERT INTO rate_limits(key,attempts) VALUES($1,1)
    ON CONFLICT(key) DO UPDATE SET attempts=CASE WHEN rate_limits.window_start < now()-interval '15 minutes' THEN 1 ELSE rate_limits.attempts+1 END,
    window_start=CASE WHEN rate_limits.window_start < now()-interval '15 minutes' THEN now() ELSE rate_limits.window_start END
    RETURNING attempts`,
    [key],
  );
  if (Number(rows[0]?.attempts) > (action === 'signup' ? 5 : 10))
    throw new ApiError(429, 'Too many attempts. Try again in 15 minutes.', 'RATE_LIMITED');
  if (action === 'login') {
    const accountKey = digest(`account-login:${email}`);
    const account = await db.query(
      `INSERT INTO rate_limits(key,attempts) VALUES($1,1)
      ON CONFLICT(key) DO UPDATE SET attempts=CASE WHEN rate_limits.window_start < now()-interval '15 minutes' THEN 1 ELSE rate_limits.attempts+1 END,
      window_start=CASE WHEN rate_limits.window_start < now()-interval '15 minutes' THEN now() ELSE rate_limits.window_start END RETURNING attempts`,
      [accountKey],
    );
    if (Number(account.rows[0]?.attempts) > 30)
      throw new ApiError(429, 'Too many attempts. Try again in 15 minutes.', 'RATE_LIMITED');
  }
}
