import { test, expect, request as apiRequest } from '@playwright/test';
import { randomBytes, randomUUID, createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';

test.use({ extraHTTPHeaders: { 'X-Forwarded-For': '192.0.2.62' } });

test('private iPhone pairing transfers only to its dish, resumes, reviews and revokes access', async ({
  page,
}) => {
  const origin = 'http://127.0.0.1:3000';
  const headers = { Origin: origin };
  const signup = await page.request.post('/api/auth/signup', {
    headers,
    data: {
      email: `native-${randomUUID()}@example.test`,
      password: `DishPlay-${randomUUID()}`,
      restaurantName: 'Native capture restaurant',
    },
  });
  expect(signup.status(), await signup.text()).toBe(201);
  const created = await page.request.post('/api/dishes', {
    headers,
    data: { name: 'Native dish', priceCents: 1200 },
  });
  const { dish } = await created.json();
  const native = await apiRequest.newContext({
    baseURL: origin,
    extraHTTPHeaders: { 'X-Forwarded-For': '192.0.2.63' },
  });
  const other = await apiRequest.newContext({
    baseURL: origin,
    extraHTTPHeaders: { 'X-Forwarded-For': '192.0.2.64' },
  });
  try {
    expect(
      (await page.request.post('/api/capture-links', { data: { dishId: dish.id } })).status(),
    ).toBe(403);
    expect((await page.request.get('/api/native/session')).status()).toBe(401);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/capture?dish=${dish.id}`);
    const panel = page.locator('.native-capture-panel');
    await panel.getByRole('button', { name: 'Créer un code pour l’iPhone' }).click();
    const code = await panel.locator('.native-pair-code strong').innerText();
    expect(code).toMatch(/^[A-F0-9]{4}(-[A-F0-9]{4}){3}$/);
    const deviceSecret = randomBytes(32).toString('hex');
    const claim = () => native.post('/api/native/pair', { data: { code, deviceSecret } });
    expect(
      (
        await native.post('/api/native/pair', {
          headers: { Origin: 'https://foreign.example' },
          data: { code, deviceSecret },
        })
      ).status(),
    ).toBe(403);
    const paired = await claim();
    expect(paired.status(), await paired.text()).toBe(200);
    const received = await paired.json();
    expect((await (await claim()).json()).scan.id).toBe(received.scan.id);
    expect(
      (
        await native.post('/api/native/pair', {
          data: { code, deviceSecret: randomBytes(32).toString('hex') },
        })
      ).status(),
    ).toBe(409);
    const authorization = { Authorization: `Bearer ${deviceSecret}` };
    expect((await native.get('/api/restaurant', { headers: authorization })).status()).toBe(401);
    expect((await native.post('/api/native/finalize', { headers: authorization })).status()).toBe(
      400,
    );
    for (const name of ['burger', 'pasta', 'salad']) {
      const bytes = await readFile(`public/images/${name}.jpg`);
      const upload = {
        headers: {
          ...authorization,
          'Content-Type': 'image/jpeg',
          'X-Content-SHA256': createHash('sha256').update(bytes).digest('hex'),
        },
        data: bytes,
      };
      expect((await native.post('/api/native/frames', upload)).status()).toBe(201);
      expect((await native.post('/api/native/frames', upload)).status()).toBe(200);
    }
    const snapshot = await (
      await native.get('/api/native/session', { headers: authorization })
    ).json();
    expect(snapshot.hashes).toHaveLength(3);
    expect(snapshot.scan.dishId).toBe(dish.id);
    const ownerScan = await (await page.request.get(`/api/scans/${received.scan.id}`)).json();
    expect((await native.get(ownerScan.frames[0].url, { headers: authorization })).status()).toBe(
      404,
    );
    expect((await native.post('/api/native/finalize', { headers: authorization })).status()).toBe(
      200,
    );
    expect((await native.post('/api/native/finalize', { headers: authorization })).status()).toBe(
      200,
    );
    await page.reload();
    await panel.getByRole('button', { name: 'Voir les photos reçues' }).click();
    await expect(panel.getByRole('img')).toHaveCount(3);
    await panel.getByRole('button', { name: 'Choisir pour la fiche du plat' }).first().click();
    await expect(panel.getByRole('status')).toContainText('Photo ajoutée au brouillon');
    const workspace = await (await page.request.get('/api/restaurant')).json();
    expect(workspace.dishes[0].imageId).toBe(ownerScan.frames[0].mediaId);
    const published = await page.request.post('/api/publish', {
      headers,
      data: { version: workspace.restaurant.version },
    });
    expect(published.status()).toBe(200);
    expect((await native.get(ownerScan.frames[0].url)).status()).toBe(200);
    const listed = await (await page.request.get(`/api/capture-links?dishId=${dish.id}`)).json();
    expect(JSON.stringify(listed)).not.toContain(deviceSecret);
    expect(JSON.stringify(listed)).not.toContain('token_hash');
    expect(
      (
        await other.post('/api/auth/signup', {
          headers,
          data: {
            email: `other-${randomUUID()}@example.test`,
            password: `DishPlay-${randomUUID()}`,
            restaurantName: 'Other restaurant',
          },
        })
      ).status(),
    ).toBe(201);
    expect(
      (await other.delete(`/api/capture-links/${listed.links[0].id}`, { headers })).status(),
    ).toBe(404);
    expect(
      (await other.post('/api/capture-links', { headers, data: { dishId: dish.id } })).status(),
    ).toBe(404);
    await panel.getByRole('button', { name: 'Révoquer l’accès' }).click();
    await expect(panel.getByText('Accès révoqué', { exact: false })).toBeVisible();
    expect((await native.get('/api/native/session', { headers: authorization })).status()).toBe(
      401,
    );
    expect(
      (await (await page.request.get(`/api/scans/${received.scan.id}`)).json()).frames,
    ).toHaveLength(3);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.goto(`/en/capture?dish=${dish.id}`);
    await expect(page.getByRole('button', { name: 'Create a code for iPhone' })).toBeVisible();
    await expect(
      page.getByRole('heading', { name: 'Film your dish. See it in 3D.' }),
    ).toBeVisible();
  } finally {
    await native.dispose();
    await other.dispose();
  }
});
