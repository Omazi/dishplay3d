// Run against a production build on localhost, one browser/context at a time.
// Optional audit tools live outside the app: npm install --prefix /tmp/dishplay-verification axe-core@4.13.0 jsqr@1.4.0
import { chromium } from 'playwright';
import { createRequire } from 'node:module';
import { mkdir, writeFile, readFile } from 'node:fs/promises';
import sharp from 'sharp';
const require = createRequire(import.meta.url);
const toolsRoot = process.env.LANDING_AUDIT_TOOLS || '/tmp/dishplay-verification/node_modules';
const jsQR = require(`${toolsRoot}/jsqr`);
const axe = await readFile(`${toolsRoot}/axe-core/axe.min.js`, 'utf8');
const base = process.env.LANDING_AUDIT_URL || 'http://127.0.0.1:3000';
const out = '.data/landing-redesign/verification';
await mkdir(out, { recursive: true });
const report = { browser: '', pages: [], metrics: [], qr: [] };
const browser = await chromium.launch({
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || '/opt/google/chrome/chrome',
  headless: true,
  args: [
    '--enable-unsafe-swiftshader',
    '--renderer-process-limit=1',
    '--js-flags=--max-old-space-size=128',
    '--in-process-gpu',
    '--no-zygote',
  ],
});
report.browser = browser.version();
try {
  for (const [name, viewport] of [
    ['desktop', { width: 1440, height: 900 }],
    ['tablet', { width: 820, height: 1180 }],
    ['mobile', { width: 360, height: 780 }],
  ]) {
    const context = await browser.newContext({ viewport });
    try {
      const page = await context.newPage();
      const errors = [],
        consoleErrors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      page.on('console', (message) => {
        if (message.type() === 'error') consoleErrors.push(message.text());
      });
      await page.goto(base, { waitUntil: 'networkidle' });
      await page.locator('.launch-poster').evaluate((image) => image.decode());
      const audits = [];
      for (let i = 0; i < 4; i++) {
        if (i) await page.locator('.launch-stage-bottom nav a').nth(i).click();
        await page.waitForFunction((index) => {
          const root = document.querySelector('.launch-story');
          const scene = document.querySelectorAll('.launch-scene')[index];
          return (
            Number(root?.dataset.scene) === index && Number(getComputedStyle(scene).opacity) > 0.99
          );
        }, i);
        if (i === 1)
          await page.waitForFunction(() =>
            ['ready', 'error'].includes(document.querySelector('.launch-story').dataset.status),
          );
        await page.screenshot({ path: `${out}/${name}-${i}.png` });
        await page.evaluate(axe);
        const result = await page.evaluate(() =>
          axe.run(document.querySelector('.dishplay-launch'), {
            runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa'] },
          }),
        );
        audits.push({
          scene: i,
          violations: result.violations.map((v) => ({
            id: v.id,
            impact: v.impact,
            nodes: v.nodes.map((n) => ({ target: n.target, summary: n.failureSummary })),
          })),
          incomplete: result.incomplete.map((v) => ({
            id: v.id,
            nodes: v.nodes.map((n) => n.target),
          })),
        });
      }
      await page.locator('#comment-ca-marche').scrollIntoViewIfNeeded();
      await page.screenshot({ path: `${out}/${name}-creator.png` });
      await page.locator('.launch-faq').scrollIntoViewIfNeeded();
      await page.screenshot({ path: `${out}/${name}-faq.png` });
      report.pages.push({
        name,
        viewport,
        errors,
        consoleErrors,
        audits,
        overflow: await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),
      });
      // Decode the actual server-generated image, then verify the exact public URL it contains.
      if (name === 'desktop')
        for (const locale of ['', '/en']) {
          await page.goto(base + locale);
          const src = await page.locator('.launch-qr img').getAttribute('src');
          const { data, info } = await sharp(Buffer.from(src.split(',')[1], 'base64'))
            .ensureAlpha()
            .raw()
            .toBuffer({ resolveWithObject: true });
          const decoded = jsQR(new Uint8ClampedArray(data), info.width, info.height)?.data;
          const response = decoded ? await page.request.get(decoded) : null;
          report.qr.push({ locale: locale || 'fr', decoded, status: response?.status() });
        }
    } finally {
      await context.close();
    }
  }
  for (let sample = 1; sample <= 3; sample++) {
    const context = await browser.newContext({
      viewport: { width: 360, height: 780 },
      deviceScaleFactor: 2,
      isMobile: true,
      hasTouch: true,
    });
    try {
      const page = await context.newPage(),
        cdp = await context.newCDPSession(page);
      await cdp.send('Network.enable');
      await cdp.send('Network.setCacheDisabled', { cacheDisabled: true });
      await cdp.send('Network.emulateNetworkConditions', {
        offline: false,
        latency: 150,
        downloadThroughput: 1_600_000 / 8,
        uploadThroughput: 750_000 / 8,
      });
      await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 });
      await page.addInitScript(() => {
        window.landingMetrics = { lcp: 0, cls: 0 };
        new PerformanceObserver((list) => {
          for (const e of list.getEntries()) {
            window.landingMetrics.lcp = e.startTime;
            window.landingMetrics.lcpElement = e.element?.tagName;
          }
        }).observe({ type: 'largest-contentful-paint', buffered: true });
        let sessionStart = 0,
          last = 0,
          total = 0;
        new PerformanceObserver((list) => {
          for (const e of list.getEntries()) {
            if (e.hadRecentInput) continue;
            if (e.startTime - last > 1000 || e.startTime - sessionStart > 5000) {
              sessionStart = e.startTime;
              total = 0;
            }
            total += e.value;
            last = e.startTime;
            window.landingMetrics.cls = Math.max(window.landingMetrics.cls, total);
          }
        }).observe({ type: 'layout-shift', buffered: true });
      });
      await page.goto(base, { waitUntil: 'load' });
      await page.waitForTimeout(7000);
      report.metrics.push({
        sample,
        viewport: '360×780, DPR 2',
        network: '1.6 Mbps down / 0.75 Mbps up / 150 ms latency',
        cpuSlowdown: 4,
        coldCache: true,
        origin: 'localhost production build',
        ...(await page.evaluate(() => ({
          ...window.landingMetrics,
          models: performance
            .getEntriesByType('resource')
            .filter((r) => /\.(glb|usdz)/.test(r.name)).length,
          transferBytes: performance
            .getEntriesByType('resource')
            .reduce((n, r) => n + r.transferSize, 0),
        }))),
      });
    } finally {
      await context.close();
    }
  }
} finally {
  await browser.close();
  await writeFile(`${out}/report.json`, JSON.stringify(report, null, 2));
}
console.log(JSON.stringify(report, null, 2));
