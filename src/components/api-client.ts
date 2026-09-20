export class ApiClientError extends Error {
  constructor(
    message: string,
    public status: number,
    public code?: string,
  ) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body && !(init.body instanceof Blob) ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new ApiClientError(
      data.error || 'La demande a échoué. Réessayez.',
      response.status,
      data.code,
    );
  return data as T;
}

export function formatPrice(cents: number, currency: string, locale = 'fr-FR') {
  return new Intl.NumberFormat(locale, { style: 'currency', currency }).format(cents / 100);
}
