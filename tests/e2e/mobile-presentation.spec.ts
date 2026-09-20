import { test, expect, type Page } from '@playwright/test';

async function scrollStory(page: Page, fraction: number) {
  await page.locator('.story-scroll-track').evaluate((track, progress) => {
    const sticky = track.querySelector<HTMLElement>('.story-sticky')!;
    const top = parseFloat(getComputedStyle(sticky).top);
    const start = track.getBoundingClientRect().top + scrollY - top;
    const distance = (track as HTMLElement).offsetHeight - sticky.offsetHeight;
    window.scrollTo({ top: start + distance * progress, behavior: 'instant' });
  }, fraction);
}

test('all three food photographs remain inside mobile and desktop screens in both languages', async ({
  page,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  for (const route of ['/', '/en']) {
    await page.goto(route);
    for (const width of [320, 375, 390, 430, 768, 1280]) {
      await page.setViewportSize({ width, height: 844 });
      await page.locator('.premium-food-gallery').scrollIntoViewIfNeeded();
      const photos = page.locator('.premium-food-gallery figure');
      await expect(photos).toHaveCount(3);
      for (const photo of await photos.all()) {
        await expect(photo.locator('img')).toBeVisible();
        await expect
          .poll(() =>
            photo.evaluate((element) => {
              const rect = element.getBoundingClientRect();
              return rect.left >= -1 && rect.right <= innerWidth + 1 && rect.width >= 100;
            }),
          )
          .toBe(true);
        await expect(photo.locator('figcaption')).toBeVisible();
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
    }
  }
  expect(errors).toEqual([]);
});

test('scrolling explains all three chapters and manual controls still work', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.goto('/en');
  const track = page.locator('.story-scroll-track');
  await expect(track).toHaveAttribute('data-scroll', 'true');
  for (const [fraction, chapter] of [
    [0.1, '0'],
    [0.5, '1'],
    [0.85, '2'],
  ] as const) {
    await scrollStory(page, fraction);
    await expect(page.getByRole('tabpanel')).toHaveAttribute('data-chapter', chapter);
    await expect
      .poll(() =>
        page.locator('.story-sticky').evaluate((element) => {
          const box = element.getBoundingClientRect();
          return box.top >= 0 && box.bottom <= innerHeight;
        }),
      )
      .toBe(true);
  }
  await page.getByRole('tab', { name: '02 Create' }).click();
  await page.getByRole('button', { name: 'Increase demo price' }).click();
  await expect(page.locator('.story-price output')).toHaveText('€22.50');
  await page.getByRole('button', { name: 'Publish in the demo' }).click();
  await expect(page.getByRole('button', { name: 'Preview updated' })).toBeVisible();
  await page.getByRole('tab', { name: '01 Capture' }).focus();
  await page.keyboard.press('End');
  await expect(page.getByRole('tab', { name: '03 Share' })).toBeFocused();
  await page.getByRole('link', { name: 'Open this demo menu' }).click();
  await expect(page).toHaveURL(/\/en\/menu\/demo$/);
});

test('short screens and reduced motion keep every chapter accessible without scroll pinning', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.locator('.story-scroll-track')).toHaveAttribute('data-scroll', 'true');
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await expect(page.locator('.story-scroll-track')).toHaveAttribute('data-scroll', 'false');
  await expect(page.locator('.premium-food-gallery')).not.toHaveClass(/gallery-motion/);
  await page.getByRole('tab', { name: '03 Partagez' }).click();
  await expect(page.getByRole('tabpanel')).toHaveAttribute('data-chapter', '2');
  for (const viewport of [
    { width: 320, height: 568 },
    { width: 844, height: 390 },
  ]) {
    await page.setViewportSize(viewport);
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await expect(page.locator('.story-scroll-track')).toHaveAttribute('data-scroll', 'false');
    await page.getByRole('tab', { name: '02 Composez' }).click();
    await expect(page.getByRole('button', { name: 'Publier dans la démo' })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    expect(
      await page.locator('.story-scroll-track').evaluate((element) => element.style.height),
    ).toBe('');
  }
});
