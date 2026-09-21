import { test, expect } from '@playwright/test';
import type { ModelViewerElement } from '@google/model-viewer';

const modelTimeout = 25_000;
for (const [name, id, width] of [
  ['burger', 'burger', 0.16],
  ['Pasta', 'pasta', 0.26],
  ['salad', 'salad', 0.24],
] as const) {
  test(`demo ${id} exposes scaled, textured AR files and delegates AR launch`, async ({
    page,
    request,
  }) => {
    await page.goto('/en/menu/demo');
    await page.getByRole('button', { name: new RegExp('Discover.*' + name, 'i') }).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByRole('button', { name: '3D', exact: true }).click();
    const viewer = dialog.locator('model-viewer');
    await expect
      .poll(() => viewer.evaluate((el) => (el as ModelViewerElement).loaded), {
        timeout: modelTimeout,
      })
      .toBe(true);
    await expect(dialog.getByText('Illustration · approximate AR size')).toBeVisible();
    await expect(
      dialog.getByRole('link', { name: id === 'burger' ? 'CC BY-SA 4.0' : 'CC BY 4.0' }),
    ).toBeVisible();
    const dimensions = await viewer.evaluate((el) => (el as ModelViewerElement).getDimensions());
    expect(Math.max(dimensions.x, dimensions.z)).toBeCloseTo(width, 2);
    await expect(viewer).toHaveAttribute('ios-src', `/models/${id}-illustration.usdz`);
    const response = await request.get(`/models/${id}-illustration.usdz`);
    expect(response.ok()).toBe(true);
    expect(response.headers()['content-type']).toContain('model/vnd.usdz+zip');
    expect((await response.body()).subarray(0, 4).toString('hex')).toBe('504b0304');
    // Native camera/Quick Look needs a real phone. Verify the actual launcher boundary here.
    await viewer.evaluate((el) => {
      Object.defineProperty(el, 'canActivateAR', { configurable: true, value: true });
      (el as ModelViewerElement).activateAR = async () => {
        el.setAttribute('data-ar-requested', 'true');
      };
    });
    await dialog.getByRole('button', { name: 'View on my table' }).click();
    await expect(viewer).toHaveAttribute('data-ar-requested', 'true');
    await dialog.getByRole('button', { name: 'Close dish' }).click();
  });
}
