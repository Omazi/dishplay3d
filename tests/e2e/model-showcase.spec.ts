import { test, expect } from '@playwright/test';
import type { ModelViewerElement } from '@google/model-viewer';

const modelTimeout = 25_000;
test('three original photos have interactive relief; all three illustrative models load only on demand', async ({
  page,
}) => {
  test.setTimeout(120_000);
  const models: string[] = [],
    errors: string[] = [];
  page.on('request', (request) => {
    if (/\.(glb|usdz)(\?|$)/.test(request.url())) models.push(request.url());
  });
  page.on('pageerror', (error) => errors.push(error.message));
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/en');
  const section = page.locator('#experience-3d');
  expect(models).toEqual([]);
  expect(await page.evaluate(() => !!customElements.get('model-viewer'))).toBe(false);
  for (const [name, id] of [
    ['The burger', 'burger'],
    ['The pasta', 'pasta'],
    ['The salad', 'salad'],
  ]) {
    await section.getByRole('button', { name: new RegExp(name + '$') }).click();
    await section.getByRole('button', { name: 'Explore this photo', exact: true }).click();
    await expect(section.locator('.photo-scene')).toHaveAttribute('data-status', 'ready');
    await expect(section.locator('.photo-source')).toHaveAttribute('src', `/images/${id}.jpg`);
    const canvas = section.locator('canvas');
    const before = await canvas.screenshot();
    await section.getByRole('slider').fill('85');
    await expect.poll(async () => !(await canvas.screenshot()).equals(before)).toBe(true);
    await section.getByRole('button', { name: 'Close', exact: true }).click();
    await expect(canvas).toHaveCount(0);
  }
  expect(models).toEqual([]);
  await section.getByRole('button', { name: '360° view', exact: true }).click();
  for (const [name, id] of [
    ['The burger', 'burger'],
    ['The pasta', 'pasta'],
    ['The salad', 'salad'],
  ]) {
    await section.getByRole('button', { name: new RegExp(name + '$') }).click();
    await expect(section.locator('.dish-model')).toHaveAttribute('data-status', 'ready', {
      timeout: modelTimeout,
    });
    const viewer = section.locator('model-viewer');
    expect(await viewer.evaluate((el) => (el as ModelViewerElement).loaded)).toBe(true);
    expect(await viewer.evaluate((el) => (el as ModelViewerElement).autoRotate)).toBe(false);
    await expect(viewer).toHaveAttribute('src', `/models/${id}-illustration.glb`);
    await expect(section.getByText('ILLUSTRATIVE 3D MODEL', { exact: true })).toBeVisible();
    await expect(section.getByRole('link', { name: 'CC BY 4.0' })).toBeVisible();
  }
  expect(models.every((url) => /\/models\/(burger|pasta|salad)-illustration\.glb$/.test(url))).toBe(
    true,
  );
  await section.getByRole('button', { name: 'Photo with depth', exact: true }).click();
  await expect(section.locator('model-viewer')).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});

test('rotation pauses off screen and dragging gives control to the visitor', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.goto('/');
  const section = page.locator('#experience-3d');
  await section.getByRole('button', { name: 'Vue à 360°', exact: true }).click();
  await expect(section.locator('.dish-model')).toHaveAttribute('data-status', 'ready', {
    timeout: modelTimeout,
  });
  const viewer = section.locator('model-viewer');
  await viewer.scrollIntoViewIfNeeded();
  await expect
    .poll(() => viewer.evaluate((el) => (el as ModelViewerElement).autoRotate))
    .toBe(true);
  await page.evaluate(() => scrollTo({ top: 0, behavior: 'instant' }));
  await expect
    .poll(() => viewer.evaluate((el) => (el as ModelViewerElement).autoRotate))
    .toBe(false);
  await viewer.scrollIntoViewIfNeeded();
  await expect
    .poll(() => viewer.evaluate((el) => (el as ModelViewerElement).autoRotate))
    .toBe(true);
  const box = (await viewer.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 80, box.y + box.height / 2, { steps: 10 });
  await page.mouse.up();
  await expect(section.getByRole('button', { name: 'Lancer la rotation' })).toBeVisible();
  expect(await viewer.evaluate((el) => (el as ModelViewerElement).autoRotate)).toBe(false);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await section.getByRole('button', { name: 'Vue initiale', exact: true }).click();
  await expect
    .poll(() => viewer.evaluate((el) => (el as ModelViewerElement).getCameraOrbit().theta))
    .toBeCloseTo(0, 2);
});

test('failed model retains its real poster and retry fetches a new cache key', async ({ page }) => {
  await page.route('**/models/burger-illustration.glb', (route) =>
    route.fulfill({ status: 503, body: 'Unavailable' }),
  );
  await page.goto('/en');
  const section = page.locator('#experience-3d');
  await section.getByRole('button', { name: '360° view', exact: true }).click();
  await expect(section.getByRole('alert')).toContainText('3D could not start');
  await expect(section.getByRole('img')).toBeVisible();
  await expect(section.locator('model-viewer')).toHaveCount(0);
  await page.unroute('**/models/burger-illustration.glb');
  await section.getByRole('button', { name: 'Retry 3D' }).click();
  await expect(section.locator('.dish-model')).toHaveAttribute('data-status', 'ready', {
    timeout: modelTimeout,
  });
});

test('without WebGL the original photo remains visible and the effect reports failure', async ({
  page,
}) => {
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (
      this: HTMLCanvasElement,
      kind: string,
      ...args: unknown[]
    ) {
      if (kind === 'webgl') return null;
      return Reflect.apply(original, this, [kind, ...args]);
    } as typeof original;
  });
  await page.goto('/en');
  const section = page.locator('#experience-3d');
  await section.getByRole('button', { name: 'Explore this photo', exact: true }).click();
  await expect(section.getByRole('alert')).toBeVisible();
  await expect(section.locator('.photo-source')).toBeVisible();
  await expect(section.locator('canvas')).toHaveCount(0);
});
