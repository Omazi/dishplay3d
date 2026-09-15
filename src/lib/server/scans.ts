import { type Queryable, type Row } from './db';
import { ApiError } from './domain';

export function scanFromRow(row: Row) {
  return {
    id: String(row.id),
    dishId: String(row.dish_id),
    state: String(row.state),
    frameCount: Number(row.frame_count || 0),
    createdAt: new Date(String(row.created_at)).toISOString(),
    manifestHash: row.manifest_hash ? String(row.manifest_hash) : null,
  };
}
export async function ownedScan(
  tx: Queryable,
  id: string,
  restaurantId: string,
  lock = false,
): Promise<Row> {
  const { rows } = await tx.query(
    `SELECT * FROM scan_sessions WHERE id=$1 AND restaurant_id=$2${lock ? ' FOR UPDATE' : ''}`,
    [id, restaurantId],
  );
  if (!rows[0]) throw new ApiError(404, 'Capture not found.', 'NOT_FOUND');
  return rows[0];
}
export async function scanFrames(tx: Queryable, scanId: string) {
  const { rows } = await tx.query(
    'SELECT * FROM scan_frames WHERE scan_id=$1 ORDER BY created_at,id',
    [scanId],
  );
  return rows.map((row) => ({
    id: String(row.id),
    mediaId: String(row.media_id),
    sha256: String(row.sha256),
    url: `/api/media/${row.media_id}`,
    metadata: row.metadata as Record<string, unknown>,
  }));
}
