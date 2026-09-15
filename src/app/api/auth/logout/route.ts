import { NextResponse } from 'next/server';
import { api } from '@/lib/server/http';
import { database } from '@/lib/server/db';
import { digest, secureCookie, SESSION_COOKIE } from '@/lib/server/auth';

export const POST = api(async (request) => {
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (token)
    await (await database()).query('DELETE FROM sessions WHERE token_hash=$1', [digest(token)]);
  const response = NextResponse.json({ ok: true });
  response.cookies.set(SESSION_COOKIE, '', {
    httpOnly: true,
    secure: secureCookie(),
    sameSite: 'lax',
    path: '/',
    maxAge: 0,
  });
  return response;
});
