import { test, expect, type APIRequestContext } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { createHash, randomUUID } from 'node:crypto';
import { technicalViewerFixture } from '../fixtures/viewer-model';

const origin = 'http://127.0.0.1:3000';
const headers = { Origin: origin };

test('public menu is usable on mobile without camera or 3D downloads', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => {
    Object.defineProperty(navigator.mediaDevices, 'getUserMedia', {
      value: () => {
        throw new Error('Customer menu must not request a camera');
      },
    });
  });
  const heavyRequests: string[] = [];
  const browserErrors: string[] = [];
  page.on('request', (request) => {
    if (/\.(glb|usdz)(\?|$)|model-viewer/.test(request.url())) heavyRequests.push(request.url());
  });
  page.on('pageerror', (error) => browserErrors.push(error.message));
  await page.goto('/menu/demo');
  await expect(page.getByRole('heading', { name: 'Atelier des saveurs' })).toBeVisible();
  await expect(page.getByText(/Menu de démonstration/)).toBeVisible();
  await page.getByRole('button', { name: 'Découvrir Le burger de l’atelier', exact: true }).click();
  await expect(page.locator('dialog[open]')).toBeVisible();
  await page.getByRole('button', { name: 'Fermer le plat' }).click();
  await expect(page.locator('dialog[open]')).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(heavyRequests).toEqual([]);
  expect(browserErrors).toEqual([]);
});

test('accounts isolate drafts, publish atomically and retain their stable menu URL', async ({
  playwright,
  page,
}) => {
  const owner = await playwright.request.newContext({ baseURL: origin, extraHTTPHeaders: headers });
  const other = await playwright.request.newContext({ baseURL: origin, extraHTTPHeaders: headers });
  const publicClient = await playwright.request.newContext({ baseURL: origin });
  const email = `owner-${randomUUID()}@example.test`;
  const password = `DishPlay-test-${randomUUID()}`;
  const signup = await owner.post('/api/auth/signup', {
    data: { email, password, restaurantName: 'Test Bistro' },
  });
  expect(signup.status(), await signup.text()).toBe(201);
  expect((await owner.get('/api/auth/me')).status()).toBe(200);
  const second = await other.post('/api/auth/signup', {
    data: { email: `other-${randomUUID()}@example.test`, password, restaurantName: 'Other Bistro' },
  });
  expect(second.status(), await second.text()).toBe(201);
  const workspace = async (client: APIRequestContext = owner) =>
    (await client.get('/api/restaurant')).json();
  const initial = await workspace();
  const menuPath = `/api/menus/${initial.restaurant.slug}`;
  expect((await publicClient.get(menuPath)).status()).toBe(404);
  expect((await publicClient.get('/api/restaurant')).status()).toBe(401);
  const categoryResponse = await owner.post('/api/categories', { data: { name: 'Plats' } });
  expect(categoryResponse.status()).toBe(201);
  const { category } = await categoryResponse.json();
  const photo = await owner.post('/api/media', {
    headers: { 'Content-Type': 'image/jpeg' },
    data: await readFile('public/images/burger.jpg'),
  });
  expect(photo.status(), await photo.text()).toBe(201);
  const media = await photo.json();
  expect((await publicClient.get(media.url)).status()).toBe(404);
  expect((await other.get(media.url)).status()).toBe(404);
  const creation = await owner.post('/api/dishes', {
    data: {
      name: 'Le vrai plat',
      description: 'Essai de publication',
      priceCents: 1850,
      categoryId: category.id,
      imageId: media.id,
      allergens: ['Gluten'],
      isAvailable: true,
    },
  });
  expect(creation.status(), await creation.text()).toBe(201);
  let { dish } = await creation.json();
  expect(
    (
      await other.patch(`/api/dishes/${dish.id}`, {
        data: { version: dish.version, priceCents: 1 },
      })
    ).status(),
  ).toBe(404);
  expect(
    (
      await other.post('/api/dishes', {
        data: { name: 'Cross tenant', priceCents: 100, imageId: media.id },
      })
    ).status(),
  ).toBe(400);
  const publish = async () =>
    owner.post('/api/publish', { data: { version: (await workspace()).restaurant.version } });
  let publication = await publish();
  expect(publication.ok(), await publication.text()).toBe(true);
  expect((await publicClient.get(media.url)).status()).toBe(200);
  const jobsBefore = await (await owner.get('/api/reconstruction')).json();
  const changed = await owner.patch(`/api/dishes/${dish.id}`, {
    data: { version: dish.version, priceCents: 2050 },
  });
  expect(changed.ok(), await changed.text()).toBe(true);
  expect(
    (
      await owner.patch(`/api/dishes/${dish.id}`, {
        data: { version: dish.version, priceCents: 1 },
      })
    ).status(),
  ).toBe(409);
  dish = (await changed.json()).dish;
  expect((await (await publicClient.get(menuPath)).json()).dishes[0].priceCents).toBe(1850);
  publication = await publish();
  expect(publication.ok(), await publication.text()).toBe(true);
  const updatedPublic = await (await publicClient.get(menuPath)).json();
  expect(updatedPublic.restaurant.slug).toBe(initial.restaurant.slug);
  expect(updatedPublic.dishes[0].priceCents).toBe(2050);
  expect(await (await owner.get('/api/reconstruction')).json()).toEqual(jobsBefore);
  expect((await owner.post('/api/reconstruction', { data: { dishId: dish.id } })).status()).toBe(
    503,
  );
  // Retrying a frame upload must not duplicate the original, and finalization freezes inputs.
  const scanCreation = await owner.post('/api/scans', { data: { dishId: dish.id } });
  expect(scanCreation.status(), await scanCreation.text()).toBe(201);
  const { scan } = await scanCreation.json();
  const scanPath = `/api/scans/${scan.id}`;
  expect((await other.get(scanPath)).status()).toBe(404);
  let firstFrameId = '';
  for (const name of ['burger', 'pasta', 'salad']) {
    const bytes = await readFile(`public/images/${name}.jpg`);
    const sha256 = createHash('sha256').update(bytes).digest('hex');
    const options = {
      headers: { 'Content-Type': 'image/jpeg', 'X-Content-Sha256': sha256 },
      data: bytes,
    };
    const upload = await owner.post(`${scanPath}/frames`, options);
    expect(upload.status(), await upload.text()).toBe(201);
    if (name === 'burger') {
      firstFrameId = (await upload.json()).frame.id;
      const retry = await owner.post(`${scanPath}/frames`, options);
      expect(retry.status()).toBe(200);
      expect((await retry.json()).frame.id).toBe(firstFrameId);
      const mismatch = await owner.post(`${scanPath}/frames`, {
        ...options,
        headers: { ...options.headers, 'X-Content-Sha256': '0'.repeat(64) },
      });
      expect(mismatch.status()).toBe(400);
    }
  }
  const finalized = await owner.post(`${scanPath}/finalize`, { data: {} });
  expect(finalized.ok(), await finalized.text()).toBe(true);
  const finalState = (await finalized.json()).scan;
  expect(finalState.state).toBe('finalized');
  expect(finalState.frameCount).toBe(3);
  expect(
    (await (await owner.post(`${scanPath}/finalize`, { data: {} })).json()).scan.manifestHash,
  ).toBe(finalState.manifestHash);
  const lateFrame = await owner.post(`${scanPath}/frames`, {
    headers: { 'Content-Type': 'image/jpeg' },
    data: await readFile('public/images/burger.jpg'),
  });
  expect(lateFrame.status()).toBe(409);
  expect(
    (
      await owner.patch(`/api/dishes/${dish.id}`, {
        headers: { Origin: 'https://attacker.invalid' },
        data: { version: dish.version, priceCents: 1 },
      })
    ).status(),
  ).toBe(403);
  const unsupported = await owner.post('/api/media', {
    headers: { 'Content-Type': 'image/svg+xml' },
    data: '<svg onload="alert(1)"/>',
  });
  expect(unsupported.status()).toBe(400);
  expect((await owner.post('/api/auth/logout', { data: {} })).ok()).toBe(true);
  expect((await owner.get('/api/auth/me')).status()).toBe(401);
  expect((await owner.post('/api/auth/login', { data: { email, password } })).ok()).toBe(true);
  expect((await workspace()).dishes[0].priceCents).toBe(2050);
  // Load the real viewer only after an explicit 3D click; the triangle is a technical test fixture.
  const modelUrl = 'https://assets.example.test/technical-test.glb';
  const modelChange = await owner.patch(`/api/dishes/${dish.id}`, {
    data: { version: dish.version, modelGlbUrl: modelUrl },
  });
  expect(modelChange.ok(), await modelChange.text()).toBe(true);
  expect((await publish()).ok()).toBe(true);
  let requestedModels = 0;
  await page.route(modelUrl, (route) => {
    requestedModels++;
    return route.fulfill({
      contentType: 'model/gltf-binary',
      body: technicalViewerFixture(),
      headers: { 'Access-Control-Allow-Origin': '*' },
    });
  });
  await page.goto(`/menu/${initial.restaurant.slug}`);
  await page.getByRole('button', { name: 'Découvrir Le vrai plat', exact: true }).click();
  expect(requestedModels).toBe(0);
  await page.getByRole('button', { name: '3D', exact: true }).click();
  await expect.poll(() => requestedModels).toBe(1);
  await expect
    .poll(() =>
      page
        .locator('model-viewer')
        .evaluate((element) => (element as HTMLElement & { loaded: boolean }).loaded),
    )
    .toBe(true);
  await page.getByRole('button', { name: 'Photo', exact: true }).click();
  await expect(page.locator('model-viewer')).toHaveCount(0);
  await Promise.all([owner.dispose(), other.dispose(), publicClient.dispose()]);
});

test('landing, signup and capture render without horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const path of ['/', '/signup', '/capture']) {
    await page.goto(path);
    await expect(page.locator('h1')).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
      path,
    ).toBe(true);
  }
  const fileInputs = page.locator('input[type=file]');
  expect(await fileInputs.count()).toBeGreaterThan(0);
});
