import test from 'node:test';
import assert from 'node:assert/strict';
import { createTranslator, localizePath } from '../src/lib/i18n';
import { formatPrice } from '../src/components/api-client';

test('language paths preserve queries, anchors, API URLs and legacy QR addresses', () => {
  assert.equal(localizePath('/capture?dish=abc#guide', 'en'), '/en/capture?dish=abc#guide');
  assert.equal(localizePath('/en/menu/restaurant', 'fr'), '/menu/restaurant');
  assert.equal(localizePath('/fr/login', 'en'), '/en/login');
  assert.equal(localizePath('/en', 'fr'), '/');
  assert.equal(localizePath('/', 'en'), '/en');
  assert.equal(localizePath('/api/media/image', 'en'), '/api/media/image');
  assert.equal(localizePath('https://example.com/file.glb', 'en'), 'https://example.com/file.glb');
});

test('translations preserve inserted content and use the requested currency format', () => {
  assert.equal(createTranslator('en')('Découvrir {0}', ['Crème {1}']), 'Discover Crème {1}');
  assert.equal(createTranslator('fr')('Découvrir {0}', ['Crème']), 'Découvrir Crème');
  assert.equal(createTranslator('en')('constructor'), 'constructor');
  assert.equal(formatPrice(1850, 'EUR', 'en-GB'), '€18.50');
  assert.match(formatPrice(1850, 'EUR', 'fr-FR'), /18,50\s€/);
});
