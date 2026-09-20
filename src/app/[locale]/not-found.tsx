'use client';
import { useI18n, LanguageSwitcher } from '@/components/language';

import { LocalizedLink as Link } from '@/components/language';
import { Brand } from '@/components/brand';
export default function NotFound() {
  const { t } = useI18n();
  return (
    <main className="standalone-state" id="main">
      <LanguageSwitcher />
      <Brand />
      <p className="eyebrow">{t('CETTE TABLE N’EST PAS ENCORE DRESSÉE')}</p>
      <h1>{t('Page introuvable.')}</h1>
      <p>{t('Le lien est peut-être incorrect, ou ce menu n’a pas encore été publié.')}</p>
      <Link className="button button-blue" href="/">
        {' '}
        {t('Retour à l’accueil')}{' '}
      </Link>
    </main>
  );
}
