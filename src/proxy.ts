import { NextResponse, type NextRequest } from 'next/server';

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (/^\/(en|fr)(\/|$)/.test(pathname)) return NextResponse.next();
  const url = request.nextUrl.clone();
  // Keep existing French URLs and printed QR codes working without a redirect.
  url.pathname = `/fr${pathname === '/' ? '' : pathname}`;
  return NextResponse.rewrite(url);
}

export const config = {
  matcher: ['/((?!api(?:/|$)|_next(?:/|$)|.*\\.[^/]+$).*)'],
};
