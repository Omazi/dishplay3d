import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createHash } from 'node:crypto';
import { mkdtemp, readdir, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {
  canonicalJSON,
  scanManifest,
  manifestDigest,
  frameMetadataHeader,
} from '../src/lib/server/capture-manifest';
import { LocalCaptureBlobStore } from '../src/lib/server/capture-blob-store';

const sha = (value: string | Uint8Array) => createHash('sha256').update(value).digest('hex');
const scan = {
  manifest_schema: 2,
  source_type: 'video',
  capture_metadata: { lens: 'wide', intrinsics: { fx: 1200, fy: 1200 } },
};
const frames = [0, 1, 2].map((i) => ({
  sha256: sha(String(i)),
  frame_index: i,
  timestamp_ms: i * 233,
  width: 640,
  height: 480,
  metadata: { exposureDuration: 0.01 },
}));
const identity = (value = frames, capture = scan) => manifestDigest(scanManifest(capture, value));
test('schema 1 retains exact old serialization and unordered identity', () => {
  const value = [{ sha256: 'b' }, { sha256: 'a' }];
  const expected = sha(JSON.stringify({ schema: 1, frames: ['a', 'b'] }));
  assert.equal(manifestDigest(scanManifest({}, value)), expected);
  assert.equal(manifestDigest(scanManifest({ manifest_schema: 1 }, value.reverse())), expected);
});
test('schema 2 identity includes sequence, timestamps, content, dimensions and camera metadata', () => {
  const baseline = identity();
  assert.equal(
    identity([...frames].reverse()),
    baseline,
    'arrival order is irrelevant; explicit frame indexes are canonical',
  );
  assert.notEqual(
    identity(frames.map((f, i) => ({ ...f, sha256: frames[2 - i].sha256 }))),
    baseline,
  );
  assert.notEqual(
    identity(frames.map((f, i) => ({ ...f, timestamp_ms: f.timestamp_ms + (i === 1 ? 1 : 0) }))),
    baseline,
  );
  assert.notEqual(
    identity(frames.map((f, i) => ({ ...f, sha256: i === 1 ? sha('changed') : f.sha256 }))),
    baseline,
  );
  assert.notEqual(identity(frames.map((f) => ({ ...f, width: 320 }))), baseline);
  assert.notEqual(
    identity(frames, { ...scan, capture_metadata: { ...scan.capture_metadata, lens: 'tele' } }),
    baseline,
  );
  assert.notEqual(
    identity(frames.map((f) => ({ ...f, metadata: { exposureDuration: 0.02 } }))),
    baseline,
  );
  assert.equal(
    canonicalJSON({ b: 1, a: { y: 2, x: 3 } }),
    canonicalJSON({ a: { x: 3, y: 2 }, b: 1 }),
  );
});
test('invalid sequences fail rather than sorting by SHA or inventing timestamps', () => {
  assert.throws(() => identity(frames.map((f) => ({ ...f, frame_index: 0 }))));
  assert.throws(() => identity(frames.map((f) => ({ ...f, timestamp_ms: -1 }))));
  assert.throws(() => identity(frames.map((f) => ({ ...f, timestamp_ms: 2 - f.frame_index }))));
  assert.throws(() => scanManifest(scan, [{ sha256: 'x' }]));
  assert.throws(() =>
    frameMetadataHeader(new Request('http://localhost', { headers: { 'x-frame-metadata': 'no' } })),
  );
});
test('raw video identity binds bytes and capture metadata; does not depend on storage provider', () => {
  const video = { sha256: sha('video'), byte_size: 500, mime_type: 'video/mp4', storage_key: 'a' };
  const hash = manifestDigest(scanManifest(scan, [], video));
  assert.equal(manifestDigest(scanManifest(scan, [], { ...video, storage_key: 'b' })), hash);
  assert.notEqual(
    manifestDigest(scanManifest(scan, [], { ...video, sha256: sha('different') })),
    hash,
  );
  assert.throws(() => scanManifest(scan, frames, video));
});
test('local video storage streams, checksums, preserves originals and removes rejected uploads', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'dishplay-video-'));
  try {
    const store = new LocalCaptureBlobStore(root);
    const bytes = Buffer.from('0000ftypisom-test-video'); // transport gate only; worker must reject this malformed container
    async function* chunks() {
      yield bytes.subarray(0, 6);
      yield bytes.subarray(6);
    }
    const blob = await store.put(chunks(), sha(bytes));
    const read: Uint8Array[] = [];
    for await (const chunk of store.read(blob.key)) read.push(chunk);
    assert.equal(Buffer.concat(read).compare(bytes), 0);
    await assert.rejects(() => store.put(chunks(), sha('wrong')));
    assert.equal((await readdir(root)).length, 1);
    await assert.rejects(async () => {
      for await (const chunk of store.read('../other')) void chunk;
    });
    async function* interrupted() {
      yield bytes;
      throw new Error('connection lost');
    }
    await assert.rejects(() => store.put(interrupted(), sha(bytes)));
    assert.equal((await readdir(root)).length, 1);
    await store.discard(blob.key);
    assert.deepEqual(await readdir(root), []);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
