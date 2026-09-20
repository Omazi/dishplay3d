import { test, expect } from '@playwright/test';
import type { ModelViewerElement } from '@google/model-viewer';

test('mobile model controls fit small screens in both languages', async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  for (const [route, view, control, done, ar] of [
    ['/', 'Vue à 360°', 'Manipuler en 3D', 'Terminer', 'Voir sur ma table'],
    ['/en', '360° view', 'Control in 3D', 'Done', 'View on my table'],
  ]) {
    await page.setViewportSize({ width: 320, height: 640 });
    await page.goto(route);
    const section = page.locator('#experience-3d');
    await section.getByRole('button', { name: view, exact: true }).click();
    await expect(section.locator('.dish-model')).toHaveAttribute('data-status', 'ready', {
      timeout: 30_000,
    });
    await section.locator('.dish-model').scrollIntoViewIfNeeded();
    const viewer = section.locator('model-viewer');
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
    if (route === '/en')
      await page.screenshot({ path: `test-results/mobile-ar-${testInfo.project.name}.png` });
  }
});
