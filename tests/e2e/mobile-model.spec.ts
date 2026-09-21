import { test, expect } from '@playwright/test';
import type { ModelViewerElement } from '@google/model-viewer';

for (const [route, view, control, done, ar] of [
  ['/menu/demo', '3D', 'Manipuler en 3D', 'Terminer', 'Voir sur ma table'],
  ['/en/menu/demo', '3D', 'Control in 3D', 'Done', 'View on my table'],
]) {
  test(`mobile model controls fit small screens: ${route}`, async ({ page }, testInfo) => {
    test.setTimeout(90_000);
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.setViewportSize({ width: 320, height: 640 });
    await page.goto(route);
    await page.getByRole('button', { name: /^(Découvrir|Discover).*burger/i }).click();
    const section = page.getByRole('dialog');
    await section.getByRole('button', { name: view, exact: true }).click();
    const viewer = section.locator('model-viewer');
    await expect
      .poll(() => viewer.evaluate((el) => (el as ModelViewerElement).loaded), { timeout: 30_000 })
      .toBe(true);
    expect(await viewer.evaluate((el) => (el as ModelViewerElement).cameraControls)).toBe(false);
    for (const label of [control, ar]) {
      const button = section.getByRole('button', { name: label, exact: true });
      await expect(button).toBeVisible();
      const box = (await button.boundingBox())!;
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(321);
      expect(box.height).toBeGreaterThanOrEqual(44);
    }
    await section.getByRole('button', { name: control, exact: true }).click();
    await expect(section.getByRole('button', { name: done, exact: true })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(await viewer.evaluate((el) => (el as ModelViewerElement).touchAction)).toBe('none');
    await section.getByRole('button', { name: done, exact: true }).click();
    expect(await viewer.evaluate((el) => (el as ModelViewerElement).disableZoom)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    if (route === '/en/menu/demo')
      await page.screenshot({ path: `test-results/mobile-ar-${testInfo.project.name}.png` });
  });
}
