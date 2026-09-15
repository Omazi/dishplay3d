import Link from 'next/link';
import { Brand } from '@/components/brand';
export default function NotFound() {
  return (
    <main className="standalone-state" id="main">
      <Brand />
      <p className="eyebrow">CETTE TABLE N’EST PAS ENCORE DRESSÉE</p>
      <h1>Page introuvable.</h1>
      <p>Le lien est peut-être incorrect, ou ce menu n’a pas encore été publié.</p>
      <Link className="button button-blue" href="/">
        Retour à l’accueil
      </Link>
    </main>
  );
}
