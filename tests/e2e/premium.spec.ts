import { test, expect } from '@playwright/test';

test('product explanation works with keyboard, translated controls and reduced motion', async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/en');
  await page.getByRole('tab', { name: '01 Capture' }).focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('tab', { name: '02 Create' })).toBeFocused();
  await expect(page.getByRole('tabpanel')).toContainText('Your menu. Your signature.');
  await page.getByRole('button', { name: 'Increase demo price' }).click();
  await expect(page.locator('.story-price output')).toHaveText('€22.50');
  await page.getByRole('button', { name: 'Publish in the demo' }).click();
  await expect(page.getByRole('button', { name: 'Preview updated' })).toBeVisible();
  await page.getByRole('tab', { name: '03 Share' }).click();
  await expect(
    page.getByRole('img', { name: 'QR code opening the DishPlay demo menu' }),
  ).toBeVisible();
  await page.getByRole('link', { name: 'Open this demo menu' }).click();
  await expect(page).toHaveURL(/\/en\/menu\/demo$/);
});

test('assisted camera checks real frame pixels, avoids unchanged frames and stops on pause', async ({
  page,
}) => {
  // Synthetic video exercises camera/UI control only, not real food reconstruction.
  await page.addInitScript(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 640;
    canvas.height = 480;
    const ctx = canvas.getContext('2d')!;
    let pattern = -1;
    const draw = () => {
      ctx.fillStyle = pattern < 0 ? '#050505' : '#555555';
      ctx.fillRect(0, 0, 640, 480);
      if (pattern >= 0)
        for (let x = 0; x < 640; x += 24)
          for (let y = 0; y < 480; y += 24) {
            ctx.fillStyle = (x / 24 + y / 24 + pattern) % 2 ? '#aaaaaa' : '#444444';
            ctx.fillRect(x, y, 20, 20);
          }
    };
    draw();
    const timer = setInterval(draw, 200);
    Object.assign(window, {
      setCapturePattern: (next: number) => {
        pattern = next;
        draw();
      },
    });
    Object.defineProperty(navigator.mediaDevices, 'getUserMedia', {
      configurable: true,
      value: async () => canvas.captureStream(5),
    });
    addEventListener('beforeunload', () => clearInterval(timer));
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/en/capture');
  await page.getByRole('button', { name: 'Open camera', exact: true }).click();
  await expect(page.getByLabel('Image checks')).toContainText('Too dark');
  await page.getByLabel('Assisted capture', { exact: true }).check();
  await page.waitForTimeout(2400); // Prove the timed capture stays blocked for bad exposure.
  await expect(page.locator('.capture-gallery-heading h2')).toContainText('0');
  await page.evaluate(() =>
    (window as unknown as { setCapturePattern: (n: number) => void }).setCapturePattern(0),
  );
  await expect(page.locator('.capture-gallery-heading h2')).toContainText('1', { timeout: 12000 });
  await page.waitForTimeout(2800); // More than the minimum shot interval; same view must not repeat.
  await expect(page.locator('.capture-gallery-heading h2')).toContainText('1');
  await page.evaluate(() =>
    (window as unknown as { setCapturePattern: (n: number) => void }).setCapturePattern(1),
  );
  await expect(page.locator('.capture-gallery-heading h2')).toContainText('2', { timeout: 12000 });
  await page.evaluate(() =>
    (window as unknown as { setCapturePattern: (n: number) => void }).setCapturePattern(-1),
  );
  await expect(page.getByLabel('Image checks')).toContainText('Too dark');
  await page.getByRole('button', { name: 'Take a photo', exact: true }).click();
  await expect(page.locator('.capture-gallery-heading h2')).toContainText('3');
  await expect(page.getByRole('heading', { name: 'Review before uploading' })).toBeVisible();
  await page
    .locator('.camera-next-pass')
    .getByRole('button', { name: 'I’ve completed the full circle' })
    .click();
  await expect(page.getByLabel('Assisted capture', { exact: true })).not.toBeChecked();
  await expect(page.locator('.camera-next-pass')).toContainText('Raise your phone');
  await page.getByRole('button', { name: 'Pause camera' }).click();
  await expect(page.getByLabel('Assisted capture', { exact: true })).not.toBeChecked();
  await expect(page.getByLabel('Assisted capture', { exact: true })).toBeDisabled();
  await expect(
    page.getByRole('heading', { name: 'Second circle, a little higher.' }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole('heading', { name: 'Second circle, a little higher.' }),
  ).toBeVisible();
  await expect(page.locator('.capture-gallery-heading h2')).toContainText('3');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
