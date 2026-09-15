import { NextResponse } from 'next/server';
import { api, jsonBody } from '@/lib/server/http';
import { ApiError, emailField } from '@/lib/server/domain';
import { database } from '@/lib/server/db';
import { createSession, limitAuth, setSession, verifyPassword } from '@/lib/server/auth';

export const POST = api(async (request) => {
  const body = await jsonBody(request);
  const email = emailField(body.email);
  if (typeof body.password !== 'string' || !body.password.length || body.password.length > 128)
    throw new ApiError(400, 'Enter your password.');
  const password = body.password;
  await limitAuth(request, email, 'login');
  const db = await database();
  const { rows } = await db.query(
    'SELECT u.id,u.email,u.password_hash,m.restaurant_id FROM users u JOIN memberships m ON m.user_id=u.id WHERE u.email=$1 ORDER BY m.restaurant_id LIMIT 1',
    [email],
  );
  // A missing account performs the same expensive derivation as an existing one.
  const hash = rows[0]
    ? String(rows[0].password_hash)
    : 'scrypt:00000000000000000000000000000000:' + '0'.repeat(128);
  const valid = await verifyPassword(password, hash);
  if (!valid || !rows[0])
    throw new ApiError(401, 'The email or password is incorrect.', 'INVALID_CREDENTIALS');
  const token = await createSession(db, String(rows[0].id));
  return setSession(
    NextResponse.json({
      user: { id: rows[0].id, email: rows[0].email },
      restaurantId: rows[0].restaurant_id,
    }),
    token,
  );
});
