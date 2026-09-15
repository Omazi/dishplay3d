// Shared browser/server guard: inspects compressed image headers without decoding pixels.
// Call before browser bitmap decoding or creating thumbnail object URLs.
export const MAX_IMAGE_BYTES = 3 * 1024 * 1024;

export class ImageValidationError extends Error {
  constructor(
    public status: 400 | 413,
    message: string,
  ) {
    super(message);
  }
}
function completeImageContainer(bytes: Uint8Array, mime: string): boolean {
  if (mime === 'image/jpeg')
    return (
      bytes.length >= 12 && bytes[bytes.length - 2] === 0xff && bytes[bytes.length - 1] === 0xd9
    );
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (mime === 'image/webp')
    return bytes.length >= 25 && view.getUint32(4, true) + 8 === bytes.length;
  if (mime === 'image/png') {
    let offset = 8;
    let hasImageData = false;
    while (offset + 12 <= bytes.length) {
      const size = view.getUint32(offset);
      const type = String.fromCharCode(...bytes.slice(offset + 4, offset + 8));
      if (size > bytes.length - offset - 12) return false;
      if (type === 'IDAT' && size > 0) hasImageData = true;
      offset += size + 12;
      if (type === 'IEND') return size === 0 && hasImageData && offset === bytes.length;
    }
  }
  return false;
}
export function imageDimensions(
  bytes: Uint8Array,
  mime: string,
): { width: number; height: number } | null {
  const read16 = (offset: number) => bytes[offset] * 256 + bytes[offset + 1];
  const read24le = (offset: number) =>
    bytes[offset] + bytes[offset + 1] * 256 + bytes[offset + 2] * 65536;
  if (
    mime === 'image/png' &&
    bytes.length >= 24 &&
    String.fromCharCode(...bytes.slice(12, 16)) === 'IHDR'
  ) {
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    return { width: view.getUint32(16), height: view.getUint32(20) };
  }
  if (mime === 'image/jpeg') {
    let index = 2;
    while (index + 4 < bytes.length) {
      if (bytes[index] !== 0xff) return null;
      while (bytes[index] === 0xff) index++;
      const marker = bytes[index++];
      if (marker === 0xd9 || marker === 0xda) return null;
      if (marker === 0x01 || (marker >= 0xd0 && marker <= 0xd8)) continue;
      const segmentLength = read16(index);
      if (segmentLength < 2 || index + segmentLength > bytes.length) return null;
      if (
        [0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf].includes(
          marker,
        )
      ) {
        if (segmentLength < 8) return null;
        return { width: read16(index + 5), height: read16(index + 3) };
      }
      index += segmentLength;
    }
  }
  if (mime === 'image/webp' && bytes.length >= 30) {
    const kind = String.fromCharCode(...bytes.slice(12, 16));
    if (kind === 'VP8X') return { width: read24le(24) + 1, height: read24le(27) + 1 };
    if (kind === 'VP8 ' && bytes[23] === 0x9d && bytes[24] === 0x01 && bytes[25] === 0x2a)
      return {
        width: (bytes[26] + bytes[27] * 256) & 0x3fff,
        height: (bytes[28] + bytes[29] * 256) & 0x3fff,
      };
  }
  if (
    mime === 'image/webp' &&
    bytes.length >= 25 &&
    String.fromCharCode(...bytes.slice(12, 16)) === 'VP8L' &&
    bytes[20] === 0x2f
  ) {
    return {
      width: 1 + bytes[21] + ((bytes[22] & 0x3f) << 8),
      height: 1 + (bytes[22] >> 6) + (bytes[23] << 2) + ((bytes[24] & 0xf) << 10),
    };
  }
  return null;
}
export function validateImageBytes(
  bytes: Uint8Array,
  mime: string,
  maxBytes = MAX_IMAGE_BYTES,
): void {
  if (bytes.length === 0) throw new ImageValidationError(400, 'The image file is empty.');
  if (bytes.length > maxBytes)
    throw new ImageValidationError(
      413,
      `Choose an image no larger than ${Math.round(maxBytes / 1024 / 1024)} MB.`,
    );
  const jpeg = bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff;
  const png = [137, 80, 78, 71, 13, 10, 26, 10].every((n, index) => bytes[index] === n);
  const ascii = (start: number, end: number) => String.fromCharCode(...bytes.slice(start, end));
  const webp = bytes.length >= 12 && ascii(0, 4) === 'RIFF' && ascii(8, 12) === 'WEBP';
  if (!(
    (mime === 'image/jpeg' && jpeg) ||
    (mime === 'image/png' && png) ||
    (mime === 'image/webp' && webp)
  ))
    throw new ImageValidationError(400, 'Only JPEG, PNG and WebP image files are accepted.');
  const dimensions = imageDimensions(bytes, mime);
  if (!dimensions || dimensions.width < 1 || dimensions.height < 1)
    throw new ImageValidationError(
      400,
      'The image dimensions could not be read. Export a standard JPEG, PNG or WebP image.',
    );
  if (
    dimensions.width > 10_000 ||
    dimensions.height > 10_000 ||
    dimensions.width * dimensions.height > 24_000_000
  )
    throw new ImageValidationError(
      413,
      'Use an image of at most 24 megapixels and 10,000 pixels per side.',
    );
  if (!completeImageContainer(bytes, mime))
    throw new ImageValidationError(
      400,
      'The image file is incomplete. Export it again before uploading.',
    );
}
