'use client';
import { useI18n, LanguageSwitcher } from '@/components/language';

import { LocalizedLink as Link } from '@/components/language';
import { ArrowUpRight } from 'lucide-react';

export function Brand({ light = false }: { light?: boolean }) {
  const { t } = useI18n();
  return (
    <Link
      href="/"
      className={`brand ${light ? 'brand-light' : ''}`}
      aria-label={t('DishPlay, accueil')}
    >
      <span className="brand-symbol" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
      dishplay<span className="brand-period">.</span>
    </Link>
  );
}

export function Header() {
  const { t } = useI18n();
  return (
    <header className="site-header">
      <div className="container nav-inner">
        <Brand />
        <nav aria-label={t('Navigation principale')}>
          <Link className="nav-text" href="/#comment-ca-marche">
            {' '}
            {t('Comment ça marche')}{' '}
          </Link>
          <Link className="nav-text" href="/menu/demo">
            {' '}
            {t('Le menu démo')}{' '}
          </Link>
          <Link className="nav-login" href="/login">
            {' '}
            {t('Se connecter')}{' '}
          </Link>
          <Link className="button button-dark button-small" href="/signup">
            {' '}
            {t('Créer ma carte')} <ArrowUpRight size={16} />
          </Link>
        </nav>
        <LanguageSwitcher />
      </div>
    </header>
  );
}

export function Footer() {
  const { t } = useI18n();
  return (
    <footer className="site-footer">
      <div className="container footer-inner">
        <Brand />
        <p>{t('De l’assiette à la découverte.')}</p>
        <div>
          <Link href="/menu/demo">{t('Menu de démonstration')}</Link>
          <Link href="/login">
            {' '}
            {t('Espace restaurant')} <ArrowUpRight size={14} />
          </Link>
        </div>
      </div>
      <div className="container footer-bottom">
        <span>© {new Date().getFullYear()} DishPlay</span>
        <span>{t('Des plats réels. Une nouvelle perspective.')}</span>
      </div>
    </footer>
  );
}
