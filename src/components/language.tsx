'use client';

import { createContext, useContext, useMemo, type ComponentProps, type ReactNode } from 'react';
import NextLink from 'next/link';
import { usePathname, useRouter as useNextRouter } from 'next/navigation';
import { createTranslator, intlLocale, localizePath, type Locale } from '@/lib/i18n';

const LanguageContext = createContext<Locale>('fr');
export function LanguageProvider({ locale, children }: { locale: Locale; children: ReactNode }) {
  return <LanguageContext.Provider value={locale}>{children}</LanguageContext.Provider>;
}
export function useI18n() {
  const locale = useContext(LanguageContext);
  return useMemo(
    () => ({ locale, t: createTranslator(locale), numberLocale: intlLocale(locale) }),
    [locale],
  );
}
export function LocalizedLink({ href, ...props }: ComponentProps<typeof NextLink>) {
  const { locale } = useI18n();
  const localized =
    typeof href === 'string'
      ? localizePath(href, locale)
      : { ...href, pathname: href.pathname ? localizePath(href.pathname, locale) : href.pathname };
  return <NextLink {...props} href={localized} />;
}
export function useRouter() {
  const router = useNextRouter();
  const { locale } = useI18n();
  return useMemo(
    () => ({
      ...router,
      push: (href: string, options?: Parameters<typeof router.push>[1]) =>
        router.push(localizePath(href, locale), options),
      replace: (href: string, options?: Parameters<typeof router.replace>[1]) =>
        router.replace(localizePath(href, locale), options),
    }),
    [router, locale],
  );
}
export function LanguageSwitcher() {
  const { locale } = useI18n();
  const pathname = usePathname();
  return (
    <nav className="language-switcher" aria-label={locale === 'en' ? 'Language' : 'Langue'}>
      {(['fr', 'en'] as const).map((language) => (
        <a
          key={language}
          href={localizePath(pathname, language)}
          hrefLang={language}
          lang={language}
          aria-label={language === 'en' ? 'English' : 'Français'}
          aria-current={locale === language ? 'page' : undefined}
          onClick={(event) => {
            // Keep a linked capture's dish ID, filters and anchors when changing language.
            event.currentTarget.href =
              localizePath(window.location.pathname, language) +
              window.location.search +
              window.location.hash;
          }}
        >
          {language.toUpperCase()}
        </a>
      ))}
    </nav>
  );
}
