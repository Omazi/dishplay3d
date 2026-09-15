import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  allergensField,
  ApiError,
  emailField,
  integerField,
  isAllowedOrigin,
  MAX_IMAGE_BYTES,
  modelUrl,
  passwordField,
  slugify,
  validateImage,
  versionField,
} from '../src/lib/server/domain';

test('CSRF origin follows validated destination Host when Next normalizes the URL', () => {
  const requestUrl = 'http://localhost:3000/api/auth/signup';
  assert.equal(isAllowedOrigin(requestUrl, 'http://127.0.0.1:3000', '127.0.0.1:3000'), true);
  assert.equal(isAllowedOrigin(requestUrl, 'http://localhost:3000', '127.0.0.1:3000'), false);
  assert.equal(isAllowedOrigin(requestUrl, 'https://attacker.example', '127.0.0.1:3000'), false);
  assert.equal(isAllowedOrigin(requestUrl, null, '127.0.0.1:3000'), false);
  assert.equal(isAllowedOrigin(requestUrl, 'null', '127.0.0.1:3000'), false);
  assert.equal(isAllowedOrigin(requestUrl, 'http://127.0.0.1:3000', '127.0.0.1:3000/evil'), false);
  assert.equal(
    isAllowedOrigin(
      requestUrl,
      'https://menu.example',
      '127.0.0.1:3000',
      'https://menu.example/path',
    ),
    true,
  );
  assert.equal(
    isAllowedOrigin('https://internal.invalid/api/dishes', 'https://menu.example', 'menu.example'),
    true,
  );
});

test('money uses bounded integer minor units and rejects fractional/negative/NaN prices', () => {
  assert.equal(integerField(1895, 'Price'), 1895);
  for (const value of [18.95, -1, NaN, Infinity, '1895', 10_000_001])
    assert.throws(() => integerField(value, 'Price'), ApiError);
});
test('model URLs require configured exact HTTPS origin and correct export extension', () => {
  const origin = 'https://assets.example.com';
  assert.equal(
    modelUrl('https://assets.example.com/dish/abc.glb', 'glb', origin),
    'https://assets.example.com/dish/abc.glb',
  );
  for (const value of [
    'http://assets.example.com/a.glb',
    'https://evil.example/a.glb',
    'https://assets.example.com.evil.com/a.glb',
    'https://user:pass@assets.example.com/a.glb',
    'https://assets.example.com/a.glb?secret=x',
    'https://assets.example.com/a.usdz',
    'file:///a.glb',
  ])
    assert.throws(() => modelUrl(value, 'glb', origin), ApiError);
  assert.throws(() => modelUrl('https://assets.example.com/a.glb', 'glb', ''), ApiError);
  assert.equal(modelUrl(null, 'glb', ''), null);
});
test('uploads enforce matching magic bytes and size before storage', () => {
  const png = new Uint8Array(
    Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5xQAAAAASUVORK5CYII=',
      'base64',
    ),
  );
  assert.doesNotThrow(() => validateImage(png, 'image/png'));
  assert.throws(() => validateImage(png, 'image/jpeg'), ApiError);
  assert.throws(
    () => validateImage(new TextEncoder().encode('<svg onload="alert(1)"></svg>'), 'image/png'),
    ApiError,
  );
  assert.throws(() => validateImage(new Uint8Array(MAX_IMAGE_BYTES + 1), 'image/png'), ApiError);
  assert.throws(() => validateImage(new Uint8Array(), 'image/png'), ApiError);
  const huge = new Uint8Array(png);
  new DataView(huge.buffer).setUint32(16, 100_000);
  assert.throws(() => validateImage(huge, 'image/png'), ApiError);
  assert.throws(() => validateImage(png.slice(0, 9), 'image/png'), ApiError);
  assert.throws(() => validateImage(png.slice(0, -1), 'image/png'), ApiError);
});
test('identity validation and stable human-readable slug prefix', () => {
  assert.equal(emailField('  OWNER@Example.com '), 'owner@example.com');
  assert.throws(() => emailField('bad'), ApiError);
  assert.throws(() => passwordField('short'), ApiError);
  assert.equal(passwordField('  twelve spaces  '), '  twelve spaces  ');
  assert.equal(slugify('Maison Étoile / Québec'), 'maison-etoile-quebec');
  assert.equal(versionField(1), 1);
  assert.throws(() => versionField(0), ApiError);
});
test('allergens are bounded declared labels without duplicates', () => {
  assert.deepEqual(allergensField(['Milk', ' Eggs ', 'Milk']), ['Milk', 'Eggs']);
  assert.throws(() => allergensField('Milk'), ApiError);
  assert.throws(() => allergensField(Array(31).fill('Milk')), ApiError);
});
