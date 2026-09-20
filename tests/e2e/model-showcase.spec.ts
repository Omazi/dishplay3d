import { test, expect } from '@playwright/test';
import type { ModelViewerElement } from '@google/model-viewer';

test('homepage loads real 3D only on demand and supports keyboard views with reduced motion', async ({
  page,
}) => {
  const models: string[] = [];
  const errors: string[] = [];
  page.on('request', (request) => {
    if (/\.(glb|usdz)(\?|$)/.test(request.url())) models.push(request.url());
  });
  page.on('pageerror', (error) => errors.push(error.message));
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/en');
  const section = page.locator('#experience-3d');
  await section.scrollIntoViewIfNeeded();
  await expect(section.getByRole('img')).toBeVisible();
  expect(models).toEqual([]);
  expect(await page.evaluate(() => !!customElements.get('model-viewer'))).toBe(false);
  await section.getByRole('button', { name: 'Explore in 3D' }).click();
  await expect(section.locator('.model-stage')).toHaveAttribute('data-status', 'ready');
  const viewer = section.locator('model-viewer');
  expect(await viewer.evaluate((element) => (element as ModelViewerElement).loaded)).toBe(true);
  expect(await viewer.evaluate((element) => (element as ModelViewerElement).autoRotate)).toBe(
    false,
  );
  expect(models).toHaveLength(1);
  expect(models[0]).toContain('/models/avocado-demo.glb');
  await section.getByRole('button', { name: 'Side view' }).focus();
  await page.keyboard.press('Enter');
  await expect(section.getByRole('button', { name: 'Side view' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await expect
    .poll(() =>
      viewer.evaluate((element) => (element as ModelViewerElement).getCameraOrbit().theta),
    )
    .toBeCloseTo((65 * Math.PI) / 180, 2);
  await section.getByRole('button', { name: 'Top view' }).click();
  await expect
    .poll(() => viewer.evaluate((element) => (element as ModelViewerElement).getCameraOrbit().phi))
    .toBeCloseTo((25 * Math.PI) / 180, 2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await section.getByRole('button', { name: 'Back to image' }).click();
  await expect(viewer).toHaveCount(0);
  await expect(section.getByRole('img')).toBeVisible();
  expect(errors).toEqual([]);
});

test('rotation pauses off screen and dragging lets the visitor control the model', async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.goto('/');
  const section = page.locator('#experience-3d');
  await section.getByRole('button', { name: 'Explorer en 3D' }).click();
  await expect(section.locator('.model-stage')).toHaveAttribute('data-status', 'ready');
  const viewer = section.locator('model-viewer');
  await expect
    .poll(() => viewer.evaluate((element) => (element as ModelViewerElement).autoRotate))
    .toBe(true);
  await page.evaluate(() => scrollTo({ top: 0, behavior: 'instant' }));
  await expect
    .poll(() => viewer.evaluate((element) => (element as ModelViewerElement).autoRotate))
    .toBe(false);
  await viewer.scrollIntoViewIfNeeded();
  await expect
    .poll(() => viewer.evaluate((element) => (element as ModelViewerElement).autoRotate))
    .toBe(true);
  const box = (await viewer.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 80, box.y + box.height / 2, { steps: 10 });
  await page.mouse.up();
  await expect(section.getByRole('button', { name: 'Lancer la rotation' })).toBeVisible();
  expect(await viewer.evaluate((element) => (element as ModelViewerElement).autoRotate)).toBe(
    false,
  );
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await section.getByRole('button', { name: 'Vue de face' }).click();
  await expect
    .poll(() =>
      viewer.evaluate((element) => (element as ModelViewerElement).getCameraOrbit().theta),
    )
    .toBeCloseTo(0, 2);
});

test('failed model keeps the preview available and can be retried', async ({ page }) => {
  await page.route('**/models/avocado-demo.glb', (route) =>
    route.fulfill({ status: 503, body: 'Unavailable' }),
  );
  await page.goto('/en');
  const section = page.locator('#experience-3d');
  await section.getByRole('button', { name: 'Explore in 3D' }).click();
  await expect(section.getByRole('alert')).toContainText('3D could not start');
  await expect(section.getByRole('img')).toBeVisible();
  await expect(section.locator('model-viewer')).toHaveCount(0);
  await page.unroute('**/models/avocado-demo.glb');
  await section.getByRole('button', { name: 'Retry 3D' }).click();
  await expect(section.locator('.model-stage')).toHaveAttribute('data-status', 'ready');
});
