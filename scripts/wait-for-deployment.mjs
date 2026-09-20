import { setTimeout } from 'node:timers/promises';

const [origin, expectedCommit, expectedSource] = process.argv.slice(2);
if (!origin?.startsWith('https://') || !/^[a-f0-9]{40}$/.test(expectedCommit || '')) {
  throw new Error('Usage: node scripts/wait-for-deployment.mjs https://site <40-character commit>');
}
const deadline = Date.now() + 12 * 60_000;
while (Date.now() < deadline) {
  try {
    const response = await fetch(new URL('/api/health', origin), {
      cache: 'no-store',
      signal: AbortSignal.timeout(15_000),
    });
    if (response.ok && (await response.json()).commit === expectedCommit) {
      if (expectedSource) {
        const source = await fetch(new URL(`/deployment.json?commit=${expectedSource}`, origin), {
          cache: 'no-store',
          signal: AbortSignal.timeout(15_000),
        });
        if (!source.ok || (await source.json()).sourceCommit !== expectedSource) {
          throw new Error('Live source commit does not match the tested source.');
        }
      }
      console.log(`Verified production commit ${expectedCommit}`);
      process.exit(0);
    }
  } catch {
    // A rollout or transient network failure is retryable; a wrong commit never passes.
  }
  console.log('Waiting for Vercel to publish the verified commit…');
  await setTimeout(15_000);
}
throw new Error(
  'Vercel did not publish the expected commit within 12 minutes. Inspect deployment logs.',
);
