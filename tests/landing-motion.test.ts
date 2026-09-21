import test from 'node:test';
import assert from 'node:assert/strict';
import { narrativeFrame, chapters } from '../src/components/landing/motion';

test('narrative framing stays on screen and is reversible across supported dimensions', () => {
  for (const [width, height] of [
    [360, 716],
    [820, 1116],
    [1440, 836],
  ]) {
    for (const p of [...chapters, 0.399, 0.401, 0.599, 0.601, 0.719, 0.721, 0.899, 0.901]) {
      const f = narrativeFrame(p, width, height);
      assert.ok(f.x > 0 && f.x < width && f.y > 0 && f.y < height);
      assert.ok(f.radius >= 99 && f.radius <= 110 && f.phi >= 66 && f.phi <= 75);
      narrativeFrame(1 - p, width, height);
      assert.deepEqual(narrativeFrame(p, width, height), f);
      const next = narrativeFrame(p + 0.0001, width, height);
      assert.ok(Math.abs(next.size - f.size) < 1 && Math.abs(next.y - f.y) < 1);
    }
    assert.equal(narrativeFrame(-1, width, height).scene, 0);
    assert.equal(narrativeFrame(2, width, height).scene, 3);
  }
});
