import { NextResponse } from 'next/server';
import { api } from '@/lib/server/http';
import { requireUser } from '@/lib/server/auth';

export const GET = api(async (request) => NextResponse.json(await requireUser(request)));
