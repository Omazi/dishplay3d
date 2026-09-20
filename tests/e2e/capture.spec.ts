import { test, expect } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { createHash, randomUUID } from 'node:crypto';
import { unzipSync } from 'fflate';

test('camera denial recovers to stable import; originals persist and export unchanged', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => {
    Object.defineProperty(navigator.mediaDevices, 'getUserMedia', {
      configurable: true,
      value: async () => {
        throw new DOMException('Test camera permission refusal', 'NotAllowedError');
      },
    });
  });
  await page.goto('/capture');
  const input = page.getByLabel('Importer les photos', { exact: true });
  await input.evaluate((element) => element.setAttribute('data-stable-input', 'retained'));
  await page.getByRole('button', { name: 'Ouvrir la caméra', exact: true }).click();
  await expect(page.locator('.notice-error[role="alert"]')).toContainText('refusé');
  await expect(input).toHaveAttribute('data-stable-input', 'retained');
  await input.setInputFiles('public/images/burger.jpg');
  await expect(page.getByRole('img', { name: 'burger.jpg', exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('img', { name: 'burger.jpg', exact: true })).toBeVisible();
  await input.setInputFiles({
    name: 'bad.svg',
    mimeType: 'image/svg+xml',
    buffer: Buffer.from('<svg/>'),
  });
  await expect(page.locator('.notice-error[role="alert"]')).toContainText('JPEG');
  await expect(page.getByRole('img', { name: 'burger.jpg', exact: true })).toBeVisible();
  const downloading = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Exporter les originaux', exact: true }).click();
  const download = await downloading;
  expect(download.suggestedFilename()).toMatch(/^dishplay-capture-.*\.zip$/);
  const file = await download.path();
  expect(file).toBeTruthy();
  const files = unzipSync(await readFile(file!));
  const originalName = Object.keys(files).find((name) => name.startsWith('images/'))!;
  const hash = (bytes: Uint8Array) => createHash('sha256').update(bytes).digest('hex');
  expect(hash(files[originalName])).toBe(hash(await readFile('public/images/burger.jpg')));
  const manifest = JSON.parse(new TextDecoder().decode(files['manifest.json']));
  expect(manifest.poses).toBeNull();
  expect(manifest.frames).toHaveLength(1);
  expect(manifest.frames[0].capture.source).toBe('import');
  expect(manifest.frames[0].capture.pass).toBeUndefined();
  expect(manifest.frames[0].capture.quality.version).toBe(1);
});

test('linked capture uploads all photos, finalizes and restores its immutable state', async ({
  page,
}) => {
  const headers = { Origin: 'http://127.0.0.1:3000' };
  const signup = await page.request.post('/api/auth/signup', {
    headers,
    data: {
      email: `capture-${randomUUID()}@example.test`,
      password: `DishPlay-${randomUUID()}`,
      restaurantName: 'Capture test',
    },
  });
  expect(signup.status(), await signup.text()).toBe(201);
  const created = await page.request.post('/api/dishes', {
    headers,
    data: { name: 'Capture liée', priceCents: 1000 },
  });
  expect(created.status(), await created.text()).toBe(201);
  const { dish } = await created.json();
  await page.goto(`/capture?dish=${dish.id}`);
  const completed = page.waitForResponse(
    (response) => response.url().endsWith('/finalize') && response.request().method() === 'POST',
  );
  await page
    .getByLabel('Importer les photos', { exact: true })
    .setInputFiles([
      'public/images/burger.jpg',
      'public/images/pasta.jpg',
      'public/images/salad.jpg',
    ]);
  await expect(page.getByRole('img', { name: 'salad.jpg', exact: true })).toBeVisible();
  const result = await completed;
  expect(result.ok()).toBe(true);
  const { scan } = await result.json();
  expect(scan.frameCount).toBe(3);
  await expect(page.getByText('Série finalisée', { exact: true })).toBeVisible();
  await expect(page.getByText(/Le calcul 3D est actuellement indisponible/)).toBeVisible();
  await page.reload();
  await expect(page.getByText('Série finalisée', { exact: true })).toBeVisible();
  await expect(page.getByRole('img', { name: 'salad.jpg', exact: true })).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Reprendre le transfert', exact: true }),
  ).toBeDisabled();
});
