import { Suspense } from 'react';
import { Capture } from '@/components/capture';
import { createTranslator, isLocale } from '@/lib/i18n';
import { localizedMetadata } from '@/lib/i18n/metadata';
export const generateMetadata = localizedMetadata('Capture photo guidée', true);
export default async function CapturePage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  const t = createTranslator(isLocale(locale) ? locale : 'fr');
  return (
    <Suspense
      fallback={
        <main id="main" className="standalone-state">
          {t('Ouverture de l’atelier…')}
        </main>
      }
    >
      <Capture />
    </Suspense>
  );
}
