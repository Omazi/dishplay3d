'use client';
import Link from 'next/link';
export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <main className="standalone-state" id="main">
      <p className="eyebrow">UN PETIT CONTRETEMPS</p>
      <h1>La page n’a pas pu charger.</h1>
      <p>Vérifiez votre connexion et réessayez.</p>
      <button className="button button-blue" onClick={reset}>
        Réessayer
      </button>
      <Link href="/">Retour à l’accueil</Link>
    </main>
  );
}
