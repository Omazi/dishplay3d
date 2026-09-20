import { NextResponse } from 'next/server';
import { api, jsonBody } from '@/lib/server/http';
import { requireUser } from '@/lib/server/auth';
import { database } from '@/lib/server/db';
import { idField } from '@/lib/server/domain';
import { issueCaptureLink } from '@/lib/server/native-capture';
export const POST = api(async (request) => {
  const identity = await requireUser(request);
  const body = await jsonBody(request);
  return NextResponse.json(
    await issueCaptureLink(await database(), identity, idField(body.dishId)),
    { status: 201 },
  );
});
export const GET = api(async (request) => {
  const identity = await requireUser(request);
  const dishId = idField(request.nextUrl.searchParams.get('dishId'));
  const { rows } = await (
    await database()
  ).query(
    `SELECT l.id,l.scan_id AS "scanId",l.code_expires_at AS "codeExpiresAt",l.token_expires_at AS "tokenExpiresAt",l.claimed_at AS "claimedAt",l.revoked_at AS "revokedAt",s.state,
    (SELECT count(*)::integer FROM scan_frames f WHERE f.scan_id=s.id) AS "frameCount"
    FROM native_capture_links l LEFT JOIN scan_sessions s ON s.id=l.scan_id WHERE l.restaurant_id=$1 AND l.dish_id=$2 ORDER BY l.created_at DESC LIMIT 20`,
    [identity.restaurantId, dishId],
  );
  return NextResponse.json({ links: rows });
});
