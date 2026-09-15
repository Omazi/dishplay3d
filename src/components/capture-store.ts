import { validateImageBytes } from '@/lib/image-validation';

export interface CaptureFrame {
  id: string;
  sessionId: string;
  name: string;
  type: string;
  size: number;
  createdAt: string;
}

function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (!('indexedDB' in window)) {
      reject(
        new Error(
          'Le stockage local est indisponible dans ce navigateur. Essayez Safari ou Chrome hors navigation privée.',
        ),
      );
      return;
    }
    const request = indexedDB.open('dishplay-captures', 1);
    request.onupgradeneeded = () => {
      const db = request.result;
      db.createObjectStore('frames', { keyPath: 'id' }).createIndex('sessionId', 'sessionId');
      db.createObjectStore('originals');
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () =>
      reject(new Error('Impossible d’ouvrir le stockage local. Vérifiez l’espace libre.'));
  });
}

export async function listFrames(sessionId: string): Promise<CaptureFrame[]> {
  const db = await database();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('frames', 'readonly');
    const request = tx.objectStore('frames').index('sessionId').getAll(sessionId);
    request.onsuccess = () =>
      resolve(
        (request.result as CaptureFrame[]).sort((a, b) => a.createdAt.localeCompare(b.createdAt)),
      );
    request.onerror = () => reject(request.error);
    tx.oncomplete = () => db.close();
  });
}

export async function storeFrame(
  sessionId: string,
  blob: Blob,
  name: string,
): Promise<CaptureFrame> {
  const meta: CaptureFrame = {
    id: crypto.randomUUID(),
    sessionId,
    name,
    type: blob.type,
    size: blob.size,
    createdAt: new Date().toISOString(),
  };
  const db = await database();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(['frames', 'originals'], 'readwrite');
    tx.objectStore('frames').put(meta);
    tx.objectStore('originals').put(blob, meta.id);
    tx.oncomplete = () => {
      db.close();
      resolve(meta);
    };
    tx.onerror = () => {
      db.close();
      reject(
        new Error(
          'La photo n’a pas été enregistrée. L’espace de stockage est peut-être insuffisant. Les prises précédentes sont conservées.',
        ),
      );
    };
  });
}

export async function getOriginal(id: string): Promise<Blob> {
  const db = await database();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('originals', 'readonly');
    const request = tx.objectStore('originals').get(id);
    request.onsuccess = () =>
      request.result
        ? resolve(request.result as Blob)
        : reject(new Error('Original introuvable dans ce navigateur.'));
    request.onerror = () => reject(request.error);
    tx.oncomplete = () => db.close();
  });
}

export async function removeFrame(id: string): Promise<void> {
  const db = await database();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(['frames', 'originals'], 'readwrite');
    tx.objectStore('frames').delete(id);
    tx.objectStore('originals').delete(id);
    tx.oncomplete = () => {
      db.close();
      resolve();
    };
    tx.onerror = () => {
      db.close();
      reject(tx.error);
    };
  });
}

export async function uploadCopy(blob: Blob): Promise<Blob> {
  validateImageBytes(new Uint8Array(await blob.arrayBuffer()), blob.type, 25 * 1024 * 1024);
  if (blob.size <= 3 * 1024 * 1024 && ['image/jpeg', 'image/png', 'image/webp'].includes(blob.type))
    return blob;
  const bitmap = await createImageBitmap(blob);
  try {
    const scale = Math.min(1, 1920 / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext('2d')!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const copy = await new Promise<Blob>((resolve, reject) =>
      canvas.toBlob(
        (value) =>
          value
            ? resolve(value)
            : reject(new Error('Cette image ne peut pas être convertie. Utilisez un JPEG ou PNG.')),
        'image/jpeg',
        0.88,
      ),
    );
    canvas.width = 0;
    canvas.height = 0;
    return copy;
  } finally {
    bitmap.close();
  }
}

export async function sha256(blob: Blob): Promise<string> {
  return Array.from(
    new Uint8Array(await crypto.subtle.digest('SHA-256', await blob.arrayBuffer())),
    (value) => value.toString(16).padStart(2, '0'),
  ).join('');
}
