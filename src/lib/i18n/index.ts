import english from './en.json';

export type Locale = 'fr' | 'en';
export function isLocale(value: string): value is Locale {
  return value === 'fr' || value === 'en';
}
export function localizePath(path: string, locale: Locale): string {
  if (!path.startsWith('/') || path.startsWith('//') || /^\/(api|_next)(\/|$)/.test(path))
    return path;
  const bare = path.replace(/^\/(en|fr)(?=\/|[?#]|$)/, '') || '/';
  return locale === 'en'
    ? `/en${bare === '/' ? '' : bare.startsWith('/') ? bare : `/${bare}`}`
    : bare.startsWith('/')
      ? bare
      : `/${bare}`;
}
export function createTranslator(locale: Locale) {
  return (source: string, values: Array<string | number> = []) => {
    const translated =
      locale === 'en' && Object.hasOwn(english, source)
        ? (english as Record<string, string>)[source]
        : source;
    return translated.replace(/\{(\d+)\}/g, (match, index: string) =>
      String(values[Number(index)] ?? match),
    );
  };
}
export const intlLocale = (locale: Locale) => (locale === 'en' ? 'en-GB' : 'fr-FR');
