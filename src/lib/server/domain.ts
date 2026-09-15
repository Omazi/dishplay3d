import { ImageValidationError, validateImageBytes } from '../image-validation';

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code = 'INVALID_REQUEST',
  ) {
    super(message);
  }
}
export function isAllowedOrigin(
  requestUrl: string,
  origin: string | null,
  host: string | null,
  canonicalUrl?: string,
): boolean {
  if (!origin) return false;
  const url = new URL(requestUrl);
  if (!['http:', 'https:'].includes(url.protocol)) return false;
  let destination = url.origin;
  if (host !== null) {
    // Next can normalize request.url to localhost while the browser used 127.0.0.1.
    // Host is the browser's actual destination. Never accept forwarded-host values here.
    if (!/^(\[[0-9a-f:.]+\]|[a-z0-9.-]+)(:\d{1,5})?$/i.test(host)) return false;
    try {
      destination = new URL(`${url.protocol}//${host}`).origin;
    } catch {
      return false;
    }
  }
  if (origin === destination) return true;
  if (canonicalUrl) {
    try {
      const canonical = new URL(canonicalUrl);
      return ['http:', 'https:'].includes(canonical.protocol) && origin === canonical.origin;
    } catch {
      return false;
    }
  }
  return false;
}
export function textField(value: unknown, name: string, max: number, required = false): string {
  if (typeof value !== 'string') throw new ApiError(400, `${name} must be text.`);
  const result = value.trim();
  if (result.length > max || (required && result.length === 0))
    throw new ApiError(400, `${name} must contain ${required ? '1' : '0'}–${max} characters.`);
  return result;
}
export function integerField(value: unknown, name: string, max = 10_000_000): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0 || value > max)
    throw new ApiError(400, `${name} must be a whole number between 0 and ${max}.`);
  return value;
}
export function versionField(value: unknown): number {
  const result = integerField(value, 'Version', 2_147_483_646);
  if (result < 1) throw new ApiError(400, 'A current version is required.');
  return result;
}
export function idField(value: unknown, name = 'ID'): string {
  const result = textField(value, name, 64, true);
  if (!/^[a-zA-Z0-9_-]+$/.test(result)) throw new ApiError(400, `${name} is invalid.`);
  return result;
}
export function emailField(value: unknown): string {
  const email = textField(value, 'Email', 254, true).toLowerCase();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email))
    throw new ApiError(400, 'Enter a valid email address.');
  return email;
}
export function passwordField(value: unknown): string {
  if (typeof value !== 'string' || value.length < 12 || value.length > 128)
    throw new ApiError(400, 'Use a password with 12–128 characters.');
  return value;
}
export function slugify(value: string): string {
  return (
    value
      .normalize('NFKD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '')
      .slice(0, 48) || 'restaurant'
  );
}
export function modelUrl(
  value: unknown,
  extension: 'glb' | 'usdz',
  allowedOrigin = process.env.MEDIA_PUBLIC_ORIGIN,
): string | null {
  if (value === null || value === '') return null;
  const raw = textField(value, `Model ${extension.toUpperCase()} URL`, 2048, true);
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new ApiError(400, 'Enter a valid HTTPS model URL.');
  }
  if (!allowedOrigin)
    throw new ApiError(400, 'Model imports require the operator to configure MEDIA_PUBLIC_ORIGIN.');
  let origin: string;
  try {
    origin = new URL(allowedOrigin).origin;
  } catch {
    throw new ApiError(503, 'The model asset origin is not configured correctly.');
  }
  if (
    url.protocol !== 'https:' ||
    url.origin !== origin ||
    url.username ||
    url.password ||
    !url.pathname.toLowerCase().endsWith(`.${extension}`) ||
    url.search ||
    url.hash
  ) {
    throw new ApiError(
      400,
      `Use an HTTPS .${extension} file on the configured asset origin, without credentials or query parameters.`,
    );
  }
  return url.href;
}
export { MAX_IMAGE_BYTES } from '../image-validation';
export function validateImage(bytes: Uint8Array, mime: string): void {
  try {
    validateImageBytes(bytes, mime);
  } catch (error) {
    if (error instanceof ImageValidationError) throw new ApiError(error.status, error.message);
    throw error;
  }
}
export function allergensField(value: unknown): string[] {
  if (!Array.isArray(value) || value.length > 30)
    throw new ApiError(400, 'Allergens must be a list of up to 30 labels.');
  return [...new Set(value.map((item) => textField(item, 'Allergen', 80, true)))];
}
