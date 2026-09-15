import { test, expect } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
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
});
