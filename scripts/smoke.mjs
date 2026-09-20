const origin = process.argv[2];
if (!origin || !/^https?:\/\//.test(origin))
  throw new Error('Usage: node scripts/smoke.mjs https://site');
for (const route of [
  '/',
  '/menu/demo',
  '/capture',
  '/login',
  '/en',
  '/en/menu/demo',
  '/en/capture',
  '/en/login',
  '/api/menus/demo',
]) {
  const response = await fetch(new URL(route, origin), {
    signal: AbortSignal.timeout(30_000),
    redirect: 'manual',
  });
  if (!response.ok) throw new Error(`${route}: HTTP ${response.status}`);
  if (route.startsWith('/api')) {
    const menu = await response.json();
    if (menu.restaurant?.slug !== 'demo' || !menu.dishes?.length)
      throw new Error('Demo menu content is invalid.');
  } else {
    const html = await response.text();
    const locale = route === '/en' || route.startsWith('/en/') ? 'en' : 'fr';
    if (!html.includes(`lang="${locale}"`)) throw new Error(`${route}: wrong document language`);
  }
  console.log(`PASS ${route}`);
}
