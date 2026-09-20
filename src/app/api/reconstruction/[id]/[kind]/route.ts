import { api } from '@/lib/server/http';
import { database } from '@/lib/server/db';
import { requireUser } from '@/lib/server/auth';
import { artifactPart } from '@/lib/server/reconstruction-artifacts';
export const GET = api(
  async (request, context: { params: Promise<{ id: string; kind: string }> }) => {
    const { id, kind } = await context.params;
    const identity = await requireUser(request);
    return artifactPart(
      await database(),
      identity.restaurantId,
      id,
      kind,
      request.nextUrl.searchParams.get('part'),
    );
  },
);
