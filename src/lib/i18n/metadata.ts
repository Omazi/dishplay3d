import type { Metadata } from 'next';
import { createTranslator, isLocale } from './index';

export function localizedMetadata(title: string, privatePage = false) {
  return async ({ params }: { params: Promise<{ locale: string }> }): Promise<Metadata> => {
    const { locale } = await params;
    return {
      title: createTranslator(isLocale(locale) ? locale : 'fr')(title),
      ...(privatePage ? { robots: { index: false, follow: false } } : {}),
    };
  };
}
