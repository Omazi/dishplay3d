import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { LanguageProvider } from '@/components/language';
import { createTranslator, isLocale } from '@/lib/i18n';
import '../globals.css';
import '../capture-guide.css';

export function generateStaticParams() {
  return [{ locale: 'fr' }, { locale: 'en' }];
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = createTranslator(isLocale(locale) ? locale : 'fr');
  return {
    title: {
      default: `DishPlay — ${t('Donnez une nouvelle dimension à votre carte')}`,
      template: '%s · DishPlay',
    },
    description: t(
      'Créez votre carte, photographiez vos plats et partagez un menu accessible depuis un simple QR code.',
    ),
    icons: { icon: '/favicon.svg' },
  };
}

export default async function RootLayout({
  children,
  params,
}: Readonly<{ children: React.ReactNode; params: Promise<{ locale: string }> }>) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const t = createTranslator(locale);
  return (
    <html lang={locale}>
      <body>
        <LanguageProvider locale={locale}>
          <a className="skip-link" href="#main">
            {t('Aller au contenu')}
          </a>
          {children}
        </LanguageProvider>
      </body>
    </html>
  );
}
