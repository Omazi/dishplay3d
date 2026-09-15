import Link from 'next/link';
import { ArrowUpRight } from 'lucide-react';

export function Brand({ light = false }: { light?: boolean }) {
  return (
    <Link href="/" className={`brand ${light ? 'brand-light' : ''}`} aria-label="DishPlay, accueil">
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
  return (
    <header className="site-header">
      <div className="container nav-inner">
        <Brand />
        <nav aria-label="Navigation principale">
          <Link className="nav-text" href="/#comment-ca-marche">
            Comment ça marche
          </Link>
          <Link className="nav-text" href="/menu/demo">
            Le menu démo
          </Link>
          <Link className="nav-login" href="/login">
            Se connecter
          </Link>
          <Link className="button button-dark button-small" href="/signup">
            Créer ma carte <ArrowUpRight size={16} />
          </Link>
        </nav>
      </div>
    </header>
  );
}

export function Footer() {
  return (
    <footer className="site-footer">
      <div className="container footer-inner">
        <Brand />
        <p>De l’assiette à la découverte.</p>
        <div>
          <Link href="/menu/demo">Menu de démonstration</Link>
          <Link href="/login">
            Espace restaurant <ArrowUpRight size={14} />
          </Link>
        </div>
      </div>
      <div className="container footer-bottom">
        <span>© {new Date().getFullYear()} DishPlay</span>
        <span>Des plats réels. Une nouvelle perspective.</span>
      </div>
    </footer>
  );
}
