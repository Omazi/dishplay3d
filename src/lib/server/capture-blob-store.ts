import { constants } from 'node:fs';
import { mkdir, open, lstat, unlink, statfs } from 'node:fs/promises';
import path from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { ApiError } from './domain';

export const MAX_VIDEO_BYTES = 256 * 1024 * 1024;
export interface CaptureBlob {
  backend: string;
  key: string;
  sha256: string;
  bytes: number;
}
/** Object-store implementations must preserve streaming, checksum and immutable-key semantics. */
export interface CaptureBlobStore {
  readonly backend: string;
  put(source: AsyncIterable<Uint8Array>, expectedSha256: string): Promise<CaptureBlob>;
  read(key: string): AsyncIterable<Uint8Array>;
  discard(key: string): Promise<void>;
}
export class LocalCaptureBlobStore implements CaptureBlobStore {
  readonly backend = 'local-v1';
  constructor(readonly root: string) {}
  private filename(key: string) {
    if (!/^[a-f0-9-]{36}\.video$/.test(key)) throw new ApiError(400, 'Invalid video storage key.');
    return path.join(this.root, key);
  }
  async put(source: AsyncIterable<Uint8Array>, expectedSha256: string): Promise<CaptureBlob> {
    if (!/^[a-f0-9]{64}$/.test(expectedSha256))
      throw new ApiError(400, 'A video SHA-256 is required.', 'CHECKSUM_MISMATCH');
    await mkdir(this.root, { recursive: true, mode: 0o700 });
    if ((await lstat(this.root)).isSymbolicLink()) throw new Error('Unsafe capture storage root');
    const space = await statfs(this.root);
    if (Number(space.bavail) * Number(space.bsize) < MAX_VIDEO_BYTES + 1024 ** 3)
      throw new ApiError(507, 'Insufficient video storage space.', 'DISK_HEADROOM');
    const key = `${randomUUID()}.video`;
    const file = await open(this.filename(key), 'wx', 0o600);
    const hash = createHash('sha256');
    let bytes = 0,
      header = Buffer.alloc(0);
    try {
      for await (const chunk of source) {
        bytes += chunk.byteLength;
        if (bytes > MAX_VIDEO_BYTES)
          throw new ApiError(413, 'Video exceeds 256 MiB.', 'VIDEO_TOO_LARGE');
        if (header.length < 12)
          header = Buffer.concat([header, Buffer.from(chunk.subarray(0, 12 - header.length))]);
        hash.update(chunk);
        let offset = 0;
        while (offset < chunk.length)
          offset += (await file.write(chunk, offset, chunk.length - offset)).bytesWritten;
      }
      if (bytes < 12 || header.toString('ascii', 4, 8) !== 'ftyp')
        throw new ApiError(400, 'An MP4/MOV ISO-BMFF container is required.', 'VIDEO_INVALID');
      const sha256 = hash.digest('hex');
      if (sha256 !== expectedSha256)
        throw new ApiError(400, 'Video checksum mismatch.', 'CHECKSUM_MISMATCH');
      await file.sync();
      return { backend: this.backend, key, sha256, bytes };
    } catch (error) {
      await unlink(this.filename(key));
      throw error;
    } finally {
      await file.close();
    }
  }
  async *read(key: string): AsyncIterable<Uint8Array> {
    const filename = this.filename(key);
    const info = await lstat(filename);
    if (!info.isFile() || info.isSymbolicLink() || info.size > MAX_VIDEO_BYTES)
      throw new Error('Unsafe video blob');
    const file = await open(filename, constants.O_RDONLY | constants.O_NOFOLLOW);
    const stream = file.createReadStream({ highWaterMark: 1024 * 1024 });
    for await (const chunk of stream) yield chunk;
  }
  async discard(key: string) {
    await unlink(this.filename(key));
  }
}
export function captureBlobStore(backend = 'local-v1'): CaptureBlobStore {
  // A Vercel /tmp file is neither durable nor shared with the Linux worker.
  if (backend !== 'local-v1' || process.env.VERCEL || !process.env.CAPTURE_VIDEO_DIR)
    throw new ApiError(
      503,
      'Configure durable shared capture storage on the local server and worker. Object storage is not configured.',
      'VIDEO_STORAGE_UNAVAILABLE',
    );
  return new LocalCaptureBlobStore(path.resolve(process.env.CAPTURE_VIDEO_DIR));
}
