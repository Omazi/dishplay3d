import test from 'node:test';
import assert from 'node:assert/strict';
import { inspectPixels, imageDifference } from '../src/lib/capture-quality';

const width = 160,
  height = 120;
function pixels(value: (x: number, y: number) => number) {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y++)
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4;
      data[i] = data[i + 1] = data[i + 2] = value(x, y);
      data[i + 3] = 255;
    }
  return data;
}
test('image checks distinguish darkness, clipping, low detail and textured midtones', () => {
  assert.deepEqual(
    inspectPixels(
      pixels(() => 12),
      width,
      height,
    ).quality.warnings,
    ['dark', 'detail'],
  );
  assert.deepEqual(
    inspectPixels(
      pixels(() => 255),
      width,
      height,
    ).quality.warnings,
    ['bright', 'detail'],
  );
  assert.deepEqual(
    inspectPixels(
      pixels(() => 120),
      width,
      height,
    ).quality.warnings,
    ['detail'],
  );
  const textured = inspectPixels(
    pixels((x, y) => ((x + y) % 5 ? 80 : 180)),
    width,
    height,
  );
  assert.deepEqual(textured.quality.warnings, []);
  assert.equal(textured.quality.version, 1);
});
test('frame difference detects change without claiming spatial movement or coverage', () => {
  const first = inspectPixels(
    pixels((x, y) => ((x + y) % 5 ? 80 : 180)),
    width,
    height,
  ).gray;
  assert.equal(imageDifference(first, first), 0);
  assert.equal(imageDifference(first, null), null);
  assert.equal(imageDifference(first, new Uint8Array(5)), null);
  const changed = inspectPixels(
    pixels((x, y) => ((x + y + 2) % 5 ? 80 : 180)),
    width,
    height,
  ).gray;
  assert.ok(imageDifference(first, changed)! > 7);
  assert.throws(() => inspectPixels(new Uint8ClampedArray(4), 1, 1));
});
