'use client';
import { useI18n, LanguageSwitcher } from '@/components/language';

import { LocalizedLink as Link } from '@/components/language';
export default function ErrorPage({ reset }: { reset: () => void }) {
  const { t } = useI18n();
  return (
    <main className="standalone-state" id="main">
      <LanguageSwitcher />
      <p className="eyebrow">{t('UN PETIT CONTRETEMPS')}</p>
      <h1>{t('La page n’a pas pu charger.')}</h1>
      <p>{t('Vérifiez votre connexion et réessayez.')}</p>
      <button className="button button-blue" onClick={reset}>
        {' '}
        {t('Réessayer')}{' '}
      </button>
      <Link href="/">{t('Retour à l’accueil')}</Link>
    </main>
  );
}
