'use client';

import { useState, type FormEvent } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ArrowRight, LoaderCircle } from 'lucide-react';
import { api } from './api-client';
import { Brand } from './brand';

export function AuthForm({ signup = false }: { signup?: boolean }) {
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
      setError(err instanceof Error ? err.message : 'Connexion impossible.');
    } finally {
      setBusy(false);
    }
  }
  return (
    <main id="main" className="auth-layout">
      <div className="auth-panel">
        <Brand />
        <div className="auth-form-wrap">
          <p className="eyebrow">VOTRE ESPACE RESTAURANT</p>
          <h1>{signup ? 'Votre carte commence ici.' : 'De retour en cuisine.'}</h1>
          <p>
            {signup
              ? 'Quelques informations, puis votre premier plat.'
              : 'Retrouvez vos plats et préparez la suite.'}
          </p>
          <form onSubmit={submit} className="form-stack">
            {signup && (
              <label>
                Nom du restaurant
                <input
                  name="restaurantName"
                  required
                  maxLength={100}
                  autoComplete="organization"
                  placeholder="L’Atelier des saveurs"
                />
              </label>
            )}
            <label>
              Adresse e-mail
              <input
                name="email"
                type="email"
                required
                autoComplete="email"
                placeholder="vous@restaurant.fr"
              />
            </label>
            <label>
              Mot de passe
              <input
                name="password"
                type="password"
                required
                minLength={signup ? 12 : 1}
                maxLength={128}
                autoComplete={signup ? 'new-password' : 'current-password'}
              />
              {signup && <span className="field-hint">12 caractères minimum.</span>}
            </label>
            {error && (
              <p className="notice notice-error" role="alert">
                {error}
              </p>
            )}
            <button className="button button-blue" disabled={busy}>
              {busy ? (
                <LoaderCircle className="spin" size={18} />
              ) : (
                <>
                  {signup ? 'Créer mon espace' : 'Se connecter'}
                  <ArrowRight size={18} />
                </>
              )}
            </button>
          </form>
          <p className="auth-switch">
            {signup ? 'Vous avez déjà un compte ?' : 'Vous ouvrez votre espace ?'}{' '}
            <Link href={signup ? '/login' : '/signup'}>
              {signup ? 'Se connecter' : 'Créer un compte'}
            </Link>
          </p>
          <Link href="/menu/demo" className="subtle-link">
            Découvrir le menu démo
          </Link>
        </div>
        <span className="auth-footnote">Votre cuisine. Votre carte. Votre signature.</span>
      </div>
      <aside className="auth-photo">
        <img src="/images/salad.jpg" alt="Photographie illustrative d’une salade colorée" />
        <div>
          <span className="eyebrow">FAITES PLACE À LA DÉCOUVERTE</span>
          <h2>
            Une belle assiette
            <br />
            mérite d’être vue.
          </h2>
          <p>Photographie d’illustration.</p>
        </div>
      </aside>
    </main>
  );
}
