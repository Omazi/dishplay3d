import { api } from '@/lib/server/http';
import { database } from '@/lib/server/db';
import { withNativeCapture } from '@/lib/server/native-capture';
import { artifactPart } from '@/lib/server/reconstruction-artifacts';
export const GET = api(
  async (request, context: { params: Promise<{ id: string; kind: string }> }) => {
    const { id, kind } = await context.params;
    return withNativeCapture(await database(), request.headers.get('authorization'), (tx, grant) =>
      artifactPart(
        tx,
        String(grant.restaurant_id),
        id,
        kind,
        request.nextUrl.searchParams.get('part'),
        String(grant.scan_id),
      ),
    );
  },
  { nativeCapability: true },
);
