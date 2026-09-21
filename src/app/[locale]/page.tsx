import Link from 'next/link';
import QRCode from 'qrcode';
import { ArrowUpRight } from 'lucide-react';
import { Brand } from '@/components/brand';
import { LanguageSwitcher } from '@/components/language';
import { isLocale, localizePath } from '@/lib/i18n';
import { localizedDemoMenu } from '@/lib/demo';
import { showcaseModels } from '@/lib/showcase-models';
import { landingCopy } from '@/components/landing/content';
import { LandingStory } from '@/components/landing/story';
import {
  Arrival,
  Exploration,
  MenuReveal,
  TableScene,
  CreatorJourney,
  LandingFAQ,
  Conclusion,
} from '@/components/landing/sections';
import '../launch.css';

export default async function Home({ params }: { params: Promise<{ locale: string }> }) {
  const { locale: value } = await params;
  const locale = isLocale(value) ? value : 'fr';
  const c = landingCopy(locale);
  const path = (href: string) => localizePath(href, locale);
  const menu = localizedDemoMenu(locale),
    dish = menu.dishes[0];
  const price = new Intl.NumberFormat(locale === 'fr' ? 'fr-FR' : 'en-GB', {
    style: 'currency',
    currency: menu.restaurant.currency,
  }).format(dish.priceCents / 100);
  const demoUrl = `https://dishplay3d.vercel.app${path('/menu/demo')}`;
  const qr = await QRCode.toDataURL(demoUrl, {
    width: 180,
    margin: 1,
    color: { dark: '#252824', light: '#f6f5f0' },
  });
  const demoLink = (
    <Link className="launch-text-link" href={path('/menu/demo')}>
      {c.openMenu}
      <ArrowUpRight size={17} />
    </Link>
  );
  return (
    <div className="dishplay-launch">
      <noscript>
        <link rel="stylesheet" href="/landing-static.css" />
      </noscript>
      <header className="launch-header">
        <Brand light />
        <nav aria-label={locale === 'fr' ? 'Navigation principale' : 'Main navigation'}>
          <a className="launch-nav-how" href="#comment-ca-marche">
            {c.how}
          </a>
          <Link className="launch-nav-demo" href={path('/menu/demo')}>
            <span className="launch-label-long">{c.navDemo}</span>
            <span className="launch-label-short">{locale === 'fr' ? 'Démo' : 'Demo'}</span>
          </Link>
          <Link className="launch-nav-login" href={path('/login')}>
            {c.login}
          </Link>
          <LanguageSwitcher />
          <Link className="launch-nav-cta" href={path('/signup')}>
            <span className="launch-label-long">{c.navCreate}</span>
            <span className="launch-label-short">{locale === 'fr' ? 'Créer' : 'Create'}</span>
            <ArrowUpRight size={14} />
          </Link>
        </nav>
      </header>
      <main id="main">
        <LandingStory
          copy={c}
          phone={
            <>
              <div className="launch-phone-speaker" />
              <div className="launch-phone-brand">
                dishplay<span>.</span>
              </div>
              <div className="launch-phone-restaurant">{menu.restaurant.name}</div>
              <div className="launch-phone-media" />
              <div className="launch-phone-info">
                <div>
                  <h3>{dish.name}</h3>
                  <strong>{price}</strong>
                </div>
                <p>{dish.description}</p>
                <span>3D · {c.illustrative}</span>
              </div>
              <div className="launch-phone-home" />
            </>
          }
        >
          <Arrival c={c} path={path} />
          <Exploration c={c} demoLink={demoLink} />
          <MenuReveal
            c={c}
            demoLink={demoLink}
            qr={qr}
            demoUrl={demoUrl}
            dish={dish}
            price={price}
          />
          <TableScene c={c} demoLink={demoLink} />
        </LandingStory>
        <CreatorJourney c={c} path={path} locale={locale} dish={dish} />
        <LandingFAQ c={c} />
        <Conclusion c={c} path={path} demoLink={demoLink} />
      </main>
      <footer className="launch-footer">
        <div>
          <Brand light />
          <p>© {new Date().getFullYear()} DishPlay</p>
          <Link href={path('/login')}>
            {c.login}
            <ArrowUpRight size={15} />
          </Link>
        </div>
        <p>
          {c.credits}{' '}
          <a href={showcaseModels[0].source} target="_blank" rel="noreferrer">
            Sketchfab
          </a>{' '}
          ·{' '}
          <a href={showcaseModels[0].licenseUrl} target="_blank" rel="noreferrer">
            {showcaseModels[0].license}
          </a>
        </p>
      </footer>
    </div>
  );
}
