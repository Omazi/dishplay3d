import { test, expect, type Page } from '@playwright/test';

export async function chapter(page: Page, index: number) {
  await page.locator('.launch-stage-bottom nav a').nth(index).click();
  await expect(page.locator('.launch-story')).toHaveAttribute('data-scene', String(index));
}

test('the shared dish and readable actions fit desktop, tablet, mobile and short screens in both languages', async ({
  page,
}) => {
  test.setTimeout(120_000);
  // Layout does not depend on network/GPU success; genuine 3D has separate tests.
  await page.route('**/*.glb*', (route) => route.abort());
  for (const locale of ['/', '/en']) {
    for (const viewport of [
      { width: 1440, height: 900 },
      { width: 820, height: 1180 },
      { width: 390, height: 844 },
      { width: 360, height: 780 },
      { width: 320, height: 568 },
      { width: 844, height: 390 },
    ]) {
      await page.setViewportSize(viewport);
      await page.goto(locale);
      await expect(page.locator('h1')).toBeVisible();
      await expect(page.locator('.launch-intro a').first()).toBeInViewport();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      if (viewport.height >= 720) {
        await expect(page.locator('.launch-story')).toHaveAttribute('data-enhanced', 'true');
        for (const index of [0, 1, 2, 3, 2, 1, 0]) {
          await chapter(page, index);
          const box = await page.locator('.launch-shared-dish').boundingBox();
          expect(box).not.toBeNull();
          expect(box!.x + box!.width / 2).toBeGreaterThan(0);
          expect(box!.x + box!.width / 2).toBeLessThan(viewport.width);
          await expect(page.locator('.launch-scene').nth(index).locator('h1,h2')).toBeInViewport();
        }
      } else {
        await expect(page.locator('.launch-story')).toHaveAttribute('data-enhanced', 'false');
        for (const scene of await page.locator('.launch-scene').all())
          await expect(scene).toBeVisible();
      }
    }
  }
});

test('reduced motion and resize restore a complete static story without downloading 3D', async ({
  page,
}) => {
  const models: string[] = [];
  page.on('request', (request) => {
    if (/\.glb/.test(request.url())) models.push(request.url());
  });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/en#menu-reveal');
  await expect(page.locator('.launch-story')).toHaveAttribute('data-enhanced', 'false');
  for (const scene of await page.locator('.launch-scene').all()) {
    await expect(scene.locator('h1,h2')).toBeVisible();
    await expect(scene.locator('.launch-static-dish')).toBeVisible();
  }
  expect(models).toEqual([]);
  await expect(page.locator('model-viewer')).toHaveCount(0);
  await page
    .locator('#menu-reveal')
    .getByRole('link', { name: 'Open the demo menu', exact: true })
    .click();
  await expect(page).toHaveURL(/\/en\/menu\/demo$/);
  await page.goto('/en');
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await expect(page.locator('.launch-story')).toHaveAttribute('data-enhanced', 'true');
  await page.setViewportSize({ width: 844, height: 390 });
  await expect(page.locator('.launch-story')).toHaveAttribute('data-enhanced', 'false');
  await expect(page.locator('#menu-reveal h2')).toBeVisible();
});
