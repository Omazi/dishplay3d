import { NextResponse } from 'next/server';
import { api } from '@/lib/server/http';
import { ApiError } from '@/lib/server/domain';
import { getPublishedMenu } from '@/lib/server/catalogue';

export const GET = api(async (_request, context: { params: Promise<{ slug: string }> }) => {
  const menu = await getPublishedMenu((await context.params).slug);
  if (!menu) throw new ApiError(404, 'This menu has not been published yet.', 'NOT_FOUND');
  return NextResponse.json(menu);
});
