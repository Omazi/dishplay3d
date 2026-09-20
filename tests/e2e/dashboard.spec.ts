import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';

test('restaurant forms create a photo dish, preview, publish and export a stable QR', async ({
  page,
}) => {
  await page.goto('/signup');
  await page.getByLabel('Nom du restaurant', { exact: true }).fill('Cuisine de test');
  await page.getByLabel('Adresse e-mail').fill(`ui-${randomUUID()}@example.test`);
  await page.getByLabel('Mot de passe').fill(`DishPlay-${randomUUID()}`);
  await page.getByRole('button', { name: 'Créer mon espace' }).click();
  // A fresh embedded PostgreSQL database must initialize on the first local signup.
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
  await page.getByRole('button', { name: 'Mon restaurant', exact: true }).click();
  const restaurantName = page.getByLabel('Nom du restaurant', { exact: true });
  await restaurantName.fill('Cuisine de test — modifiée');
  await page.getByLabel('Nouvelle catégorie', { exact: true }).fill('Plats');
  await page.getByRole('button', { name: 'Ajouter la catégorie', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('Catégorie ajoutée');
  await expect(restaurantName).toHaveValue('Cuisine de test — modifiée');
  await page.getByRole('button', { name: 'Enregistrer', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('informations du restaurant');
  await page.getByRole('button', { name: /Ma carte/ }).click();
  await page.getByRole('button', { name: 'Ajouter un plat', exact: true }).click();
  const editor = page.locator('.editor-dialog');
  await editor.getByLabel('Nom du plat', { exact: true }).fill('Assiette de test');
  await editor
    .getByLabel('Description', { exact: true })
    .fill('Une photo illustrative pour vérifier le parcours.');
  await editor.getByLabel('Prix', { exact: true }).fill('18,50');
  await editor.getByLabel('Choisir la photo du plat').setInputFiles('public/images/burger.jpg');
  await expect(editor.getByRole('img', { name: 'Photo du plat' })).toBeVisible();
  await editor.getByRole('button', { name: 'Enregistrer le plat' }).click();
  await expect(editor).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Assiette de test', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Prévisualiser', exact: true }).click();
  await expect(
    page.locator('.preview-dialog[open]').getByRole('heading', { name: 'Assiette de test' }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Fermer l’aperçu' }).click();
  await page.getByRole('button', { name: 'Publier la carte', exact: true }).click();
  await expect(page.getByText('Une version de votre carte est en ligne')).toBeVisible();
  await page.getByRole('button', { name: 'QR & partage', exact: true }).click();
  const publicLink = page.getByRole('link', { name: 'Ouvrir le lien public' });
  const stablePath = await publicLink.getAttribute('href');
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Télécharger le QR en SVG' }).click();
  const download = await downloadPromise;
  const svgPath = await download.path();
  expect(await readFile(svgPath!, 'utf8')).toContain('<svg');
  await page.getByRole('button', { name: /Ma carte/ }).click();
  await page.getByRole('button', { name: 'Modifier Assiette de test', exact: true }).click();
  await editor.getByLabel('Prix', { exact: true }).fill('20,50');
  await editor.getByRole('button', { name: 'Enregistrer le plat' }).click();
  await expect(editor).toHaveCount(0);
  await page.getByRole('button', { name: 'Publier la carte', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('Votre carte est publiée');
  await page.getByRole('button', { name: 'QR & partage', exact: true }).click();
  await expect(publicLink).toHaveAttribute('href', stablePath!);
  await page.getByRole('button', { name: 'Se déconnecter', exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto(stablePath!);
  await expect(page.getByRole('heading', { name: 'Assiette de test' })).toBeVisible();
  await expect(page.getByText(/20,50/)).toBeVisible();
});
