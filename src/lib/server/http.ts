import { NextRequest, NextResponse } from 'next/server';
import { ApiError, isAllowedOrigin } from './domain';
import { DatabaseUnavailable } from './db';

export async function readBytes(request: Request, maximum: number): Promise<Uint8Array> {
  const length = Number(request.headers.get('content-length') || 0);
  if (length > maximum) throw new ApiError(413, 'The upload is too large.');
  if (!request.body) throw new ApiError(400, 'A request body is required.');
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  while (true) {
    const part = await reader.read();
    if (part.done) break;
    size += part.value.byteLength;
    if (size > maximum) {
      await reader.cancel();
      throw new ApiError(413, 'The upload is too large.');
    }
    chunks.push(part.value);
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes;
}
export async function jsonBody(request: Request): Promise<Record<string, unknown>> {
  if (!request.headers.get('content-type')?.includes('application/json'))
    throw new ApiError(415, 'Use application/json for this request.');
  const bytes = await readBytes(request, 64 * 1024);
  try {
    const value: unknown = JSON.parse(new TextDecoder().decode(bytes));
    if (!value || typeof value !== 'object' || Array.isArray(value))
      throw new Error('object required');
    return value as Record<string, unknown>;
  } catch {
    throw new ApiError(400, 'The request body must be a valid JSON object.');
  }
}
export function checkOrigin(request: Request): void {
  if (
    !isAllowedOrigin(
      request.url,
      request.headers.get('origin'),
      request.headers.get('host'),
      process.env.NEXT_PUBLIC_APP_URL,
    )
  ) {
    throw new ApiError(403, 'This request must come from this application.', 'ORIGIN_REJECTED');
  }
}
export function api<T extends unknown[]>(
  handler: (request: NextRequest, ...args: T) => Promise<Response>,
) {
  return async (request: NextRequest, ...args: T): Promise<Response> => {
    try {
      if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method)) checkOrigin(request);
      const result = await handler(request, ...args);
      result.headers.set('X-Content-Type-Options', 'nosniff');
      if (!result.headers.has('Cache-Control')) result.headers.set('Cache-Control', 'no-store');
      return result;
    } catch (error) {
      if (error instanceof ApiError)
        return NextResponse.json(
          { error: error.message, code: error.code },
          { status: error.status, headers: { 'Cache-Control': 'no-store' } },
        );
      if (error instanceof DatabaseUnavailable)
        return NextResponse.json(
          { error: error.message, code: 'DATABASE_UNAVAILABLE' },
          { status: 503, headers: { 'Cache-Control': 'no-store' } },
        );
      console.error('API operation failed:', error instanceof Error ? error.name : 'UnknownError');
      return NextResponse.json(
        { error: 'Something went wrong. Please try again.', code: 'INTERNAL_ERROR' },
        { status: 500, headers: { 'Cache-Control': 'no-store' } },
      );
    }
  };
}
