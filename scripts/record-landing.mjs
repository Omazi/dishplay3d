// Actual Chrome screencast, encoded after the browser closes to limit RAM use.
import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
const dir = '.data/landing-redesign/scroll';
await mkdir(dir, { recursive: true });
const browser = await chromium.launch({
  executablePath: '/opt/google/chrome/chrome',
  args: [
    '--enable-unsafe-swiftshader',
    '--renderer-process-limit=1',
    '--js-flags=--max-old-space-size=128',
    '--in-process-gpu',
    '--no-zygote',
  ],
});
const frames = [],
  writes = [];
try {
  const desktop = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await desktop.goto('http://127.0.0.1:3000/', { waitUntil: 'networkidle' });
  await desktop.locator('.launch-poster').evaluate((image) => image.decode());
  await desktop.evaluate(
    () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))),
  );
  console.log(
    'Initial poster',
    await desktop.locator('.launch-poster').evaluate((image) => ({
      loaded: image.complete,
      width: image.naturalWidth,
      opacity: getComputedStyle(image).opacity,
      box: image.getBoundingClientRect().toJSON(),
    })),
  );
  await desktop.screenshot({ path: '.data/landing-redesign/verification/desktop-0.png' });
  await desktop.close();
  const page = await browser.newPage({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 1,
  });
  await page.goto('http://127.0.0.1:3000/#experience-3d');
  await page.waitForFunction(
    () => document.querySelector('.launch-story')?.dataset.status === 'ready',
  );
  await page.locator('.launch-stage-bottom nav a').first().click();
  const cdp = await page.context().newCDPSession(page);
  cdp.on('Page.screencastFrame', (frame) => {
    const name = `frame-${String(frames.length).padStart(5, '0')}.jpg`;
    frames.push({ name, time: frame.metadata.timestamp });
    writes.push(writeFile(`${dir}/${name}`, Buffer.from(frame.data, 'base64')));
    void cdp.send('Page.screencastFrameAck', { sessionId: frame.sessionId }).catch(() => {});
  });
  await cdp.send('Page.startScreencast', {
    format: 'jpeg',
    quality: 75,
    maxWidth: 390,
    maxHeight: 844,
    everyNthFrame: 2,
  });
  await page.evaluate(async () => {
    const story = document.querySelector('.launch-story');
    const start = story.getBoundingClientRect().top + scrollY - 64;
    const end = start + story.offsetHeight - innerHeight + 64;
    const run = (from, to, duration) =>
      new Promise((resolve) => {
        const begin = performance.now();
        const tick = (now) => {
          const p = Math.min(1, (now - begin) / duration);
          scrollTo({ top: from + (to - from) * p, behavior: 'instant' });
          if (p < 1) requestAnimationFrame(tick);
          else resolve();
        };
        requestAnimationFrame(tick);
      });
    await run(start, end * 0.94, 10000);
    await new Promise((resolve) => setTimeout(resolve, 1000));
    await run(end * 0.94, start, 6500);
  });
  await cdp.send('Page.stopScreencast');
} finally {
  await browser.close();
}
await Promise.all(writes);
await writeFile(`${dir}/frames.json`, JSON.stringify(frames, null, 2));
await writeFile(
  `${dir}/frames.txt`,
  frames
    .map(
      (f, i) =>
        `file '${f.name}'\nduration ${Math.max(0.016, Math.min(0.5, (frames[i + 1]?.time || f.time + 0.1) - f.time))}\n`,
    )
    .join(''),
);
execFileSync('ffmpeg', [
  '-y',
  '-loglevel',
  'error',
  '-threads',
  '1',
  '-f',
  'concat',
  '-safe',
  '0',
  '-i',
  `${dir}/frames.txt`,
  '-c:v',
  'libx264',
  '-threads',
  '1',
  '-preset',
  'veryfast',
  '-pix_fmt',
  'yuv420p',
  '-movflags',
  '+faststart',
  `${dir}/walkthrough.mp4`,
]);
console.log(
  JSON.stringify({
    frames: frames.length,
    seconds: frames.at(-1)?.time - frames[0]?.time,
    path: `${dir}/walkthrough.mp4`,
  }),
);
