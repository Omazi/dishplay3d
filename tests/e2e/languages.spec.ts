import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';

// Model a separate client so language-test retries do not consume the signup
// quota used by the independent tenant-isolation scenarios. The limiter stays active.
test.use({ extraHTTPHeaders: { 'X-Forwarded-For': '192.0.2.42' } });

test('French and English pages render on the server and switch without losing the route', async ({
  page,
  request,
}) => {
  const response = await request.get('/en');
  expect(response.status()).toBe(200);
  const html = await response.text();
  expect(html).toContain('lang="en"');
  expect(html).toContain('Give your menu a new dimension');
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/');
  await page.getByRole('link', { name: 'English', exact: true }).click();
  await expect(page).toHaveURL(/\/en$/);
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Your food.A whole new dimension.');
  await page.getByRole('link', { name: 'Demo menu', exact: true }).first().click();
  await expect(page).toHaveURL(/\/en\/menu\/demo$/);
  await expect(
    page.getByRole('heading', { name: 'The Flavour Workshop', exact: true }),
  ).toBeVisible();
  await expect(page.getByText('€18.50', { exact: true }).first()).toBeVisible();
  await page.getByRole('button', { name: 'Discover The workshop burger', exact: true }).click();
  await expect(page.locator('dialog[open]')).toContainText('Milk');
  await page.getByRole('button', { name: 'Close dish', exact: true }).click();
  await page.getByRole('link', { name: 'Français', exact: true }).click();
  await expect(page).toHaveURL(/\/menu\/demo$/);
  await expect(page.locator('html')).toHaveAttribute('lang', 'fr');
  await expect(
    page.getByRole('heading', { name: 'Atelier des saveurs', exact: true }),
  ).toBeVisible();
  for (const width of [320, 390]) {
    await page.setViewportSize({ width, height: 844 });
    for (const path of ['/en', '/en/menu/demo', '/en/signup', '/en/capture']) {
      await page.goto(path);
      await expect(page.locator('h1')).toBeVisible();
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
        `${path} at ${width}px`,
      ).toBe(true);
    }
  }
  const missing = await page.goto('/en/menu/no-such-restaurant');
  expect(missing?.status()).toBe(404);
  await expect(page.getByRole('heading', { name: 'Page not found.' })).toBeVisible();
  expect(errors).toEqual([]);
});

test('English restaurant workflow keeps user content and publishes to the same stable menu', async ({
  page,
}) => {
  await page.goto('/en/signup');
  await page.getByLabel('Restaurant name', { exact: true }).fill('Cuisine française');
  await page.getByLabel('Email address').fill(`english-${randomUUID()}@example.test`);
  await page.getByLabel('Password').fill(`DishPlay-${randomUUID()}`);
  await page.getByRole('button', { name: 'Create my workspace' }).click();
  await expect(page).toHaveURL(/\/en\/dashboard$/, { timeout: 30_000 });
  await page.getByRole('button', { name: 'Add a dish', exact: true }).click();
  const editor = page.locator('.editor-dialog');
  await editor.getByLabel('Dish name', { exact: true }).fill('Crème du marché');
  await editor.getByLabel('Description', { exact: true }).fill('Texte du restaurant conservé.');
  await editor.getByLabel('Price', { exact: true }).fill('18.50');
  await editor.getByRole('button', { name: 'Save dish' }).click();
  await expect(editor).toHaveCount(0);
  await expect(page.getByRole('status')).toContainText('Dish saved.');
  await expect(page.getByText('1 dish', { exact: true })).toBeVisible();
  await expect(page.locator('.catalogue-list').getByText('€18.50', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Publish menu', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('Your menu is published.');
  const workspace = await (await page.request.get('/api/restaurant')).json();
  expect(workspace.dishes[0].name).toBe('Crème du marché');
  await page.getByRole('button', { name: 'QR & sharing', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Open public link' })).toHaveAttribute(
    'href',
    `/en/menu/${workspace.restaurant.slug}`,
  );
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(page).toHaveURL(/\/en\/login$/);
  await page.goto(`/en/menu/${workspace.restaurant.slug}`);
  await expect(page.getByRole('heading', { name: 'Cuisine française', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Crème du marché', exact: true })).toBeVisible();
  await expect(page.getByText('Texte du restaurant conservé.')).toBeVisible();
  await page.getByRole('link', { name: 'Français', exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/menu/${workspace.restaurant.slug}$`));
  await expect(page.getByText(/18,50/)).toBeVisible();
});

test('capture translates errors and tips while preserving imported originals across languages', async ({
  page,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator.mediaDevices, 'getUserMedia', {
      configurable: true,
      value: async () => {
        throw new DOMException('Denied for test', 'NotAllowedError');
      },
    });
  });
  await page.goto('/en/capture?source=language-test#main');
  await page.getByRole('button', { name: 'Open camera', exact: true }).click();
  await expect(page.locator('.notice-error[role="alert"]')).toContainText(
    'Camera access was denied.',
  );
  await expect(page.getByRole('heading', { name: 'First circle, fairly low.' })).toBeVisible();
  await page.getByRole('button', { name: '02 The details 45°' }).click();
  await expect(
    page.getByRole('heading', { name: 'Second circle, a little higher.' }),
  ).toBeVisible();
  await page.getByLabel('Import photos', { exact: true }).setInputFiles('public/images/burger.jpg');
  await expect(page.getByRole('status')).toContainText('1 photo added.');
  await page.getByRole('link', { name: 'Français', exact: true }).click();
  await expect(page).toHaveURL(/\/capture\?source=language-test#main$/);
  await expect(page.getByRole('heading', { name: 'Gardez le bon angle.' })).toBeVisible();
  await expect(page.getByRole('img', { name: 'burger.jpg', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Un deuxième tour, plus haut.' })).toBeVisible();
});
