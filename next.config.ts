import type { NextConfig } from 'next';

const config: NextConfig = {
  poweredByHeader: false,
  serverExternalPackages: ['pg', '@electric-sql/pglite'],
  outputFileTracingIncludes: { '/*': ['./migrations/**/*.sql'] },
  experimental: { cpus: 1, webpackMemoryOptimizations: true },
  async headers() {
    return [
      {
        source: '/(.*)',
        headers: [
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          { key: 'X-Frame-Options', value: 'DENY' },
          {
            key: 'Permissions-Policy',
            value: 'camera=(self), microphone=(), geolocation=(), xr-spatial-tracking=(self)',
          },
        ],
      },
    ];
  },
};
export default config;
