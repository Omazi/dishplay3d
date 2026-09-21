import { test, expect } from '@playwright/test';
import type { ModelViewerElement } from '@google/model-viewer';

const ready = async (page: import('@playwright/test').Page) => {
  await page.goto('/en#experience-3d');
  await expect(page.locator('.launch-story')).toHaveAttribute('data-status', 'ready', {
    timeout: 30_000,
  });
};

test('one real model follows scroll, hands off its camera, resumes and releases off screen', async ({
  page,
}) => {
  const models: string[] = [],
    errors: string[] = [];
  page.on('request', (r) => {
    if (/\.(glb|usdz)/.test(r.url())) models.push(r.url());
  });
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('/en');
  expect(models).toEqual([]);
  await page.locator('.launch-stage-bottom nav a').nth(1).click();
  await expect(page.locator('.launch-story')).toHaveAttribute('data-status', 'ready', {
    timeout: 30_000,
  });
  const model = page.locator('model-viewer');
  await expect(model).toHaveCount(1);
  await expect(model).toHaveAttribute('ios-src', '/models/burger-illustration.usdz');
  await page.locator('.launch-control').click();
  await expect(page.locator('.launch-story')).toHaveAttribute('data-interactive', 'true');
  const orbit = await model.evaluate((e) => (e as ModelViewerElement).getCameraOrbit().theta);
  // The camera must stay with the user even when scroll moves to another scene.
  await page.locator('.launch-stage-bottom nav a').nth(2).click();
  expect(await model.evaluate((e) => (e as ModelViewerElement).getCameraOrbit().theta)).toBeCloseTo(
    orbit,
    3,
  );
  await page.keyboard.press('Escape');
  await expect(page.locator('.launch-stage-bottom a[aria-current="step"]')).toBeFocused();
  expect(await model.evaluate((e) => (e as ModelViewerElement).cameraControls)).toBe(false);
  await page.locator('.launch-stage-bottom nav a').nth(1).click();
  await page.locator('.launch-control').click();
  const box = (await model.boundingBox())!;
  const before = await model.evaluate((e) => (e as ModelViewerElement).getCameraOrbit().theta);
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 80, box.y + box.height / 2, { steps: 10 });
  await page.mouse.up();
  await expect
    .poll(() => model.evaluate((e) => (e as ModelViewerElement).getCameraOrbit().theta))
    .not.toBe(before);
  await page.keyboard.press('Escape');
  await page.locator('#comment-ca-marche').scrollIntoViewIfNeeded();
  await expect(model).toHaveCount(0);
  expect(models.every((url) => /burger-illustration\.glb/.test(url))).toBe(true);
  expect(errors).toEqual([]);
});

test('failed or slow model keeps the poster, retries and handles context loss', async ({
  page,
}) => {
  await page.route('**/models/burger-illustration.glb', (route) =>
    route.fulfill({ status: 503, body: 'Unavailable' }),
  );
  await page.goto('/en#experience-3d');
  await expect(page.locator('.launch-tools').getByRole('alert')).toContainText('3D is unavailable');
  await expect(page.locator('.launch-poster')).toBeVisible();
  await expect(page.locator('model-viewer')).toHaveCount(0);
  await page.unroute('**/models/burger-illustration.glb');
  await page.getByRole('button', { name: 'Retry 3D' }).click();
  await expect(page.locator('.launch-story')).toHaveAttribute('data-status', 'ready', {
    timeout: 30_000,
  });
  await page
    .locator('model-viewer')
    .evaluate((e) =>
      e.dispatchEvent(new CustomEvent('error', { detail: { type: 'webglcontextlost' } })),
    );
  await expect(page.locator('.launch-story')).toHaveAttribute('data-status', 'error');
  await expect(page.locator('.launch-poster')).toBeVisible();
});

test('without WebGL the story retains its image and direct menu links', async ({ page }) => {
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (
      this: HTMLCanvasElement,
      kind: string,
      ...args: unknown[]
    ) {
      if (kind.includes('webgl')) return null;
      return Reflect.apply(original, this, [kind, ...args]);
    } as typeof original;
  });
  await page.goto('/en#experience-3d');
  await expect(page.locator('.launch-story')).toHaveAttribute('data-status', 'error', {
    timeout: 30_000,
  });
  await expect(page.locator('.launch-poster')).toBeVisible();
  await page.locator('.launch-stage-bottom nav a').nth(2).click();
  await page
    .locator('#menu-reveal')
    .getByRole('link', { name: 'Open the demo menu', exact: true })
    .click();
  await expect(page).toHaveURL(/\/en\/menu\/demo$/);
});

test('AR is explicit and unsupported or rejected launch gives a useful fallback', async ({
  page,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator.mediaDevices, 'getUserMedia', {
      value: () => {
        throw new Error('Camera requested without consent');
      },
    });
  });
  await ready(page);
  await page.locator('.launch-stage-bottom nav a').nth(3).click();
  const model = page.locator('model-viewer');
  await model.evaluate((e) =>
    Object.defineProperty(e, 'canActivateAR', { configurable: true, value: false }),
  );
  await page.getByRole('button', { name: 'View on my table' }).click();
  await expect(page.locator('.launch-ar-message')).toContainText('Safari on iPhone');
  await model.evaluate((e) => {
    Object.defineProperty(e, 'canActivateAR', { configurable: true, value: true });
    (e as ModelViewerElement).activateAR = async () => {
      throw new Error('Unavailable');
    };
  });
  await page.getByRole('button', { name: 'View on my table' }).click();
  await expect(page.locator('.launch-ar-message')).toContainText('AR could not start');
  await model.evaluate((e) => {
    (e as ModelViewerElement).activateAR = async () => {
      e.setAttribute('data-requested-ar', 'true');
    };
  });
  await expect(model).not.toHaveAttribute('data-requested-ar', 'true');
  await page.getByRole('button', { name: 'View on my table' }).click();
  await expect(model).toHaveAttribute('data-requested-ar', 'true');
});

test('touch can scroll over the model even while deliberate 3D control is active', async ({
  browser,
}) => {
  const context = await browser.newContext({
    viewport: { width: 360, height: 780 },
    isMobile: true,
    hasTouch: true,
  });
  const page = await context.newPage();
  try {
    await ready(page);
    await page.locator('.launch-control').click();
    const model = page.locator('model-viewer');
    const cdp = await context.newCDPSession(page);
    const box = (await model.boundingBox())!;
    const x = box.x + box.width / 2,
      y = box.y + box.height * 0.6;
    const scroll = await page.evaluate(() => scrollY);
    const theta = await model.evaluate((e) => (e as ModelViewerElement).getCameraOrbit().theta);
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y }] });
    for (let i = 1; i <= 8; i++) {
      await cdp.send('Input.dispatchTouchEvent', {
        type: 'touchMove',
        touchPoints: [{ x, y: y - i * 15 }],
      });
      await page.waitForTimeout(20);
    }
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(scroll + 30);
    expect(
      await model.evaluate((e) => (e as ModelViewerElement).getCameraOrbit().theta),
    ).toBeCloseTo(theta, 2);
  } finally {
    await context.close();
  }
});

test('server HTML and no-JavaScript fallback keep all four scenes and destinations usable', async ({
  browser,
  request,
}) => {
  const response = await request.get('/en');
  const html = await response.text();
  expect(html).toContain('Your dishes.');
  expect(html).toContain('Before you choose.');
  const context = await browser.newContext({
    javaScriptEnabled: false,
    viewport: { width: 360, height: 780 },
  });
  try {
    const page = await context.newPage();
    await page.goto('/en');
    await expect(page.locator('#sur-table h2')).toBeVisible();
    await expect(page.locator('#menu-reveal h2')).toBeVisible();
    await page
      .locator('#menu-reveal')
      .getByRole('link', { name: 'Open the demo menu', exact: true })
      .click();
    await expect(page).toHaveURL(/\/en\/menu\/demo$/);
  } finally {
    await context.close();
  }
});

test('a slow model never blanks the dish while its request is pending', async ({ page }) => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route('**/models/burger-illustration.glb', async (route) => {
    await gate;
    await route.continue();
  });
  await page.goto('/en#experience-3d');
  await expect(page.locator('.launch-story')).toHaveAttribute('data-status', 'loading');
  await expect(page.locator('.launch-poster')).toBeVisible();
  await expect(page.locator('.launch-tools').getByRole('status')).toContainText('Preparing');
  release();
  await expect(page.locator('.launch-story')).toHaveAttribute('data-status', 'ready', {
    timeout: 30_000,
  });
});
