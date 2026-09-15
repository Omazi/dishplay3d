import { NextResponse } from 'next/server';
import { api, jsonBody } from '@/lib/server/http';
import { ApiError, emailField, passwordField, slugify, textField } from '@/lib/server/domain';
import { database } from '@/lib/server/db';
import { createSession, hashPassword, limitAuth, newId, setSession } from '@/lib/server/auth';

export const POST = api(async (request) => {
  const local = !process.env.VERCEL && process.env.NODE_ENV !== 'production';
  if (!local && process.env.ALLOW_SIGNUP !== 'true')
    throw new ApiError(
      403,
      'Restaurant registration is not enabled on this deployment. Contact the operator.',
      'SIGNUP_DISABLED',
    );
  const body = await jsonBody(request);
  const email = emailField(body.email);
  const password = passwordField(body.password);
  const name = textField(body.restaurantName, 'Restaurant name', 120, true);
  await limitAuth(request, email, 'signup');
  const passwordHash = await hashPassword(password);
  const db = await database();
  const userId = newId();
  const restaurantId = newId();
  const slug = `${slugify(name)}-${newId().slice(0, 8)}`;
  try {
    const token = await db.transaction(async (tx) => {
      await tx.query('INSERT INTO users(id,email,password_hash) VALUES($1,$2,$3)', [
        userId,
        email,
        passwordHash,
      ]);
      await tx.query('INSERT INTO restaurants(id,name,slug) VALUES($1,$2,$3)', [
        restaurantId,
        name,
        slug,
      ]);
      await tx.query("INSERT INTO memberships(user_id,restaurant_id,role) VALUES($1,$2,'owner')", [
        userId,
        restaurantId,
      ]);
      await tx.query('INSERT INTO qr_links(restaurant_id,slug) VALUES($1,$2)', [
        restaurantId,
        slug,
      ]);
      return createSession(tx, userId);
    });
    return setSession(
      NextResponse.json({ user: { id: userId, email }, restaurantId }, { status: 201 }),
      token,
    );
  } catch (error) {
    if (typeof error === 'object' && error && 'code' in error && error.code === '23505')
      throw new ApiError(
        409,
        'An account with this email already exists. Sign in instead.',
        'ACCOUNT_EXISTS',
      );
    throw error;
  }
});
