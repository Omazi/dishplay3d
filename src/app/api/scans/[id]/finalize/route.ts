import { NextResponse } from 'next/server';
import { api } from '@/lib/server/http';
import { digest, requireUser } from '@/lib/server/auth';
import { database } from '@/lib/server/db';
import { ApiError, idField } from '@/lib/server/domain';
import { audit, lockRestaurant } from '@/lib/server/catalogue';
import { ownedScan, scanFrames, scanFromRow } from '@/lib/server/scans';

export const POST = api(async (request, context: { params: Promise<{ id: string }> }) => {
  const identity = await requireUser(request);
  const id = idField((await context.params).id);
  const scan = await (
    await database()
  ).transaction(async (tx) => {
    await lockRestaurant(tx, identity.restaurantId);
    const previous = await ownedScan(tx, id, identity.restaurantId, true);
    if (previous.state === 'cancelled')
      throw new ApiError(409, 'This capture was cancelled.', 'SCAN_CANCELLED');
    const frames = await scanFrames(tx, id);
    if (previous.state === 'finalized')
      return { ...scanFromRow(previous), frameCount: frames.length };
    if (frames.length < 3)
      throw new ApiError(
        400,
        'Add at least three distinct photos before finalizing. This only freezes the inputs; reconstruction quality needs many overlapping views.',
      );
    const manifestHash = digest(
      JSON.stringify({ schema: 1, frames: frames.map((frame) => frame.sha256).sort() }),
    );
    const { rows } = await tx.query(
      "UPDATE scan_sessions SET state='finalized',manifest_hash=$1,finalized_at=now() WHERE id=$2 RETURNING *",
      [manifestHash, id],
    );
    await audit(tx, identity.restaurantId, identity.user.id, 'scan.finalized', {
      scanId: id,
      frameCount: frames.length,
      manifestHash,
    });
    return { ...scanFromRow(rows[0]), frameCount: frames.length };
  });
  return NextResponse.json({ scan });
});
