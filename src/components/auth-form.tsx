'use client';
import { useI18n, LanguageSwitcher } from '@/components/language';

import { useState, type FormEvent } from 'react';
import { LocalizedLink as Link } from '@/components/language';
import { useRouter } from '@/components/language';
import { ArrowRight, LoaderCircle } from 'lucide-react';
import { api } from './api-client';
import { Brand } from './brand';

export function AuthForm({ signup = false }: { signup?: boolean }) {
  const { t } = useI18n();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError('');
    const data = Object.fromEntries(new FormData(event.currentTarget));
    try {
      await api(`/api/auth/${signup ? 'signup' : 'login'}`, {
        method: 'POST',
        body: JSON.stringify(data),
      });
      router.push('/dashboard');
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : t('Connexion impossible.'));
    } finally {
      setBusy(false);
    }
  }
  return (
    <main id="main" className="auth-layout">
      <div className="auth-panel">
        <div className="auth-brand-row">
          <Brand />
          <LanguageSwitcher />
        </div>
        <div className="auth-form-wrap">
          <p className="eyebrow">{t('VOTRE ESPACE RESTAURANT')}</p>
          <h1>{signup ? t('Votre carte commence ici.') : t('De retour en cuisine.')}</h1>
          <p>
            {signup
              ? t('Quelques informations, puis votre premier plat.')
              : t('Retrouvez vos plats et préparez la suite.')}
          </p>
          <form onSubmit={submit} className="form-stack">
            {signup && (
              <label>
                {' '}
                {t('Nom du restaurant')}{' '}
                <input
                  name="restaurantName"
                  required
                  maxLength={100}
                  autoComplete="organization"
                  placeholder={t('L’Atelier des saveurs')}
                />
              </label>
            )}
            <label>
              {' '}
              {t('Adresse e-mail')}{' '}
              <input
                name="email"
                type="email"
                required
                autoComplete="email"
                placeholder="vous@restaurant.fr"
              />
            </label>
            <label>
              {' '}
              {t('Mot de passe')}{' '}
              <input
                name="password"
                type="password"
                required
                minLength={signup ? 12 : 1}
                maxLength={128}
                autoComplete={signup ? 'new-password' : 'current-password'}
              />
              {signup && <span className="field-hint">{t('12 caractères minimum.')}</span>}
            </label>
            {error && (
              <p className="notice notice-error" role="alert">
                {t(error)}
              </p>
            )}
            <button className="button button-blue" disabled={busy}>
              {busy ? (
                <LoaderCircle className="spin" size={18} />
              ) : (
                <>
                  {signup ? t('Créer mon espace') : t('Se connecter')}
                  <ArrowRight size={18} />
                </>
              )}
            </button>
          </form>
          <p className="auth-switch">
            {signup ? t('Vous avez déjà un compte ?') : t('Vous ouvrez votre espace ?')}{' '}
            <Link href={signup ? '/login' : '/signup'}>
              {signup ? t('Se connecter') : t('Créer un compte')}
            </Link>
          </p>
          <Link href="/menu/demo" className="subtle-link">
            {' '}
            {t('Découvrir le menu démo')}{' '}
          </Link>
        </div>
        <span className="auth-footnote">{t('Votre cuisine. Votre carte. Votre signature.')}</span>
      </div>
      <aside className="auth-photo">
        <img src="/images/salad.jpg" alt={t('Photographie illustrative d’une salade colorée')} />
        <div>
          <span className="eyebrow">{t('FAITES PLACE À LA DÉCOUVERTE')}</span>
          <h2>
            {' '}
            {t('Une belle assiette')} <br /> {t('mérite d’être vue.')}{' '}
          </h2>
          <p>{t('Photographie d’illustration.')}</p>
        </div>
      </aside>
    </main>
  );
}
