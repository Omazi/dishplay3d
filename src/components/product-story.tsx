'use client';
import { useEffect, useRef, useState } from 'react';
import { ArrowRight, ArrowUpRight, Check, Camera, Minus, Plus, ScanLine } from 'lucide-react';
import { LocalizedLink as Link, useI18n } from './language';
import { CaptureDiagram } from './capture-coach';
import { capturePasses } from '@/lib/capture-quality';

export function RevealMotion() {
  useEffect(() => {
    const media = matchMedia('(prefers-reduced-motion: reduce)');
    if (media.matches || !('IntersectionObserver' in window)) return;
    const gallery = document.querySelector<HTMLElement>('.premium-food-gallery');
    let frame = 0;
    const updateGallery = () => {
      frame = 0;
      if (!gallery || media.matches) return;
      const rect = gallery.getBoundingClientRect();
      const progress = Math.max(0, Math.min(1, (innerHeight - rect.top) / (innerHeight * 0.8)));
      gallery.style.setProperty('--gallery-progress', String(progress));
    };
    const scheduleGallery = () => {
      if (!frame) frame = requestAnimationFrame(updateGallery);
    };
    gallery?.classList.add('gallery-motion');
    scheduleGallery();
    window.addEventListener('scroll', scheduleGallery, { passive: true });
    window.addEventListener('resize', scheduleGallery);
    const targets = document.querySelectorAll<HTMLElement>('.premium-site [data-reveal]');
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries)
          if (entry.isIntersecting) {
            entry.target.classList.add('revealed');
            observer.unobserve(entry.target);
          }
      },
      { threshold: 0.12 },
    );
    targets.forEach((element) => {
      element.classList.add('reveal-ready');
      observer.observe(element);
    });
    const revealAll = () => {
      if (media.matches) targets.forEach((e) => e.classList.add('revealed'));
      gallery?.classList.toggle('gallery-motion', !media.matches);
      scheduleGallery();
    };
    media.addEventListener('change', revealAll);
    return () => {
      observer.disconnect();
      media.removeEventListener('change', revealAll);
      targets.forEach((e) => e.classList.remove('reveal-ready'));
      window.removeEventListener('scroll', scheduleGallery);
      window.removeEventListener('resize', scheduleGallery);
      cancelAnimationFrame(frame);
      gallery?.classList.remove('gallery-motion');
      gallery?.style.removeProperty('--gallery-progress');
    };
  }, []);
  return null;
}

const chapters = [
  {
    name: 'Capturez',
    title: 'Le bon geste. Au bon moment.',
    text: 'Le plat reste immobile. Vous faites le tour à trois hauteurs. Le guide vous aide à garder le rythme et signale les images à vérifier.',
    link: 'Essayer la capture',
    href: '/capture',
  },
  {
    name: 'Composez',
    title: 'Votre carte. Votre signature.',
    text: 'Ajoutez vos photos, descriptions, prix et allergènes. Préparez vos modifications, puis publiez-les quand tout est prêt.',
    link: 'Créer mon espace',
    href: '/signup',
  },
  {
    name: 'Partagez',
    title: 'Un QR. La curiosité fait le reste.',
    text: 'À table, le client ouvre votre menu sans compte. Vos mises à jour gardent le même lien. La photo s’affiche immédiatement, la 3D se charge à la demande.',
    link: 'Explorer le menu démo',
    href: '/menu/demo',
  },
];

export function ProductStory({ qr }: { qr: string }) {
  const { t, numberLocale } = useI18n();
  const [chapter, setChapter] = useState(0);
  const [pass, setPass] = useState(0);
  const [price, setPrice] = useState(2200);
  const [published, setPublished] = useState(false);
  const trackRef = useRef<HTMLDivElement>(null);
  const stickyRef = useRef<HTMLDivElement>(null);
  const activeChapter = useRef(0);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  useEffect(() => {
    const track = trackRef.current;
    const sticky = stickyRef.current;
    if (!track || !sticky) return;
    const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
    let frame = 0;
    let enabled = false;
    let top = 0;
    let distance = 0;
    const update = () => {
      frame = 0;
      if (!enabled) return;
      const position = top - track.getBoundingClientRect().top;
      const progress = Math.max(0, Math.min(1, position / distance));
      track.style.setProperty('--story-progress', String(progress));
      // Reading a focused control must never replace its panel during keyboard navigation.
      if (
        position < 0 ||
        position > distance ||
        (sticky.contains(document.activeElement) &&
          document.activeElement?.matches(':focus-visible'))
      )
        return;
      const next = Math.min(2, Math.floor(progress * 3));
      if (next !== activeChapter.current) {
        activeChapter.current = next;
        setChapter(next);
      }
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    const measure = () => {
      top = parseFloat(getComputedStyle(sticky).top) || 0;
      // Small/landscape screens and enlarged text keep a naturally scrolling layout.
      enabled = !reducedMotion.matches && sticky.offsetHeight + top + 24 <= innerHeight;
      distance = innerHeight * 1.65;
      track.dataset.scroll = String(enabled);
      track.style.height = enabled ? `${sticky.offsetHeight + distance}px` : '';
      schedule();
    };
    const observer = new ResizeObserver(measure);
    observer.observe(sticky);
    window.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', measure);
    reducedMotion.addEventListener('change', measure);
    measure();
    return () => {
      observer.disconnect();
      window.removeEventListener('scroll', schedule);
      window.removeEventListener('resize', measure);
      reducedMotion.removeEventListener('change', measure);
      cancelAnimationFrame(frame);
      delete track.dataset.scroll;
      track.style.height = '';
      track.style.removeProperty('--story-progress');
    };
  }, []);
  const selectChapter = (index: number) => {
    activeChapter.current = index;
    setChapter(index);
    const track = trackRef.current;
    const sticky = stickyRef.current;
    if (track?.dataset.scroll === 'true' && sticky) {
      const top = parseFloat(getComputedStyle(sticky).top) || 0;
      const distance = track.offsetHeight - sticky.offsetHeight;
      const start = track.getBoundingClientRect().top + scrollY - top;
      window.scrollTo({ top: start + ((index + 0.25) / 3) * distance, behavior: 'instant' });
    }
  };
  const priceLabel = new Intl.NumberFormat(numberLocale, {
    style: 'currency',
    currency: 'EUR',
  }).format(price / 100);
  return (
    <section
      className="product-story container"
      id="comment-ca-marche"
      aria-labelledby="story-title"
    >
      <div className="premium-section-heading" data-reveal>
        <p className="eyebrow">{t('DE L’ASSIETTE À L’ÉCRAN')}</p>
        <h2 id="story-title">
          {t('Simple à comprendre.')}
          <br />
          <span>{t('Savoureux à découvrir.')}</span>
        </h2>
        <p>{t('Explorez chaque étape. Puis passez à votre propre carte.')}</p>
      </div>
      <div className="story-scroll-track" ref={trackRef}>
        <div className="story-sticky" ref={stickyRef}>
          <div className="story-tabs" role="tablist" aria-label={t('Comment fonctionne DishPlay')}>
            {chapters.map((item, index) => (
              <button
                key={item.name}
                id={`story-tab-${index}`}
                role="tab"
                aria-selected={chapter === index}
                aria-controls="story-panel"
                tabIndex={chapter === index ? 0 : -1}
                ref={(element) => {
                  tabRefs.current[index] = element;
                }}
                onClick={() => selectChapter(index)}
                onKeyDown={(event) => {
                  const next =
                    event.key === 'ArrowRight'
                      ? (chapter + 1) % 3
                      : event.key === 'ArrowLeft'
                        ? (chapter + 2) % 3
                        : event.key === 'Home'
                          ? 0
                          : event.key === 'End'
                            ? 2
                            : null;
                  if (next !== null) {
                    event.preventDefault();
                    selectChapter(next);
                    tabRefs.current[next]?.focus();
                  }
                }}
              >
                <span>0{index + 1}</span>
                {t(item.name)}
              </button>
            ))}
          </div>
          <div
            className="story-panel"
            id="story-panel"
            role="tabpanel"
            aria-labelledby={`story-tab-${chapter}`}
            tabIndex={0}
            data-chapter={chapter}
          >
            <div className="story-text" key={`text-${chapter}`}>
              <span className="story-index">0{chapter + 1}</span>
              <h3>{t(chapters[chapter].title)}</h3>
              <p>{t(chapters[chapter].text)}</p>
              <Link href={chapters[chapter].href} className="inline-link">
                {t(chapters[chapter].link)}
                <ArrowUpRight size={18} />
              </Link>
              <p className="story-footnote">
                {chapter === 0
                  ? t('La capture web conserve des photos. Le calcul 3D est une étape séparée.')
                  : t('Démo interactive · modifications non enregistrées')}
              </p>
            </div>
            <div className="story-stage" key={`stage-${chapter}`}>
              {chapter === 0 && (
                <div className="story-capture">
                  <div className="story-stage-top">
                    <Camera size={18} />
                    <span>{t('LE GESTE À SUIVRE')}</span>
                    <span>{capturePasses[pass].angle}</span>
                  </div>
                  <CaptureDiagram pass={pass} />
                  <h4>{t(capturePasses[pass].short)}</h4>
                  <div className="story-heights">
                    {capturePasses.map((item, index) => (
                      <button
                        key={item.name}
                        aria-pressed={pass === index}
                        onClick={() => setPass(index)}
                      >
                        {item.angle}
                        <span>{t(item.name)}</span>
                      </button>
                    ))}
                  </div>
                  <p>{t('Choisissez une hauteur pour voir le mouvement conseillé.')}</p>
                </div>
              )}
              {chapter === 1 && (
                <div className="story-editor">
                  <div className="story-stage-top">
                    <span>{t('VOTRE ESPACE RESTAURANT')}</span>
                    <span className="story-draft">
                      {published ? t('Aperçu publié') : t('Brouillon démo')}
                    </span>
                  </div>
                  <img
                    src="/images/pasta.jpg"
                    width="500"
                    height="340"
                    alt={t('Photographie illustrative d’un plat de pâtes')}
                    loading="lazy"
                  />
                  <div className="story-editor-body">
                    <span className="eyebrow">{t('PLAT À LA CARTE')}</span>
                    <h4>Pasta della casa</h4>
                    <p>{t('Pâtes, tomates et herbes fraîches.')}</p>
                    <div className="story-price">
                      <span>{t('Prix')}</span>
                      <div>
                        <button
                          aria-label={t('Diminuer le prix démo')}
                          disabled={price <= 100}
                          onClick={() => {
                            setPrice((p) => p - 50);
                            setPublished(false);
                          }}
                        >
                          <Minus size={16} />
                        </button>
                        <output aria-live="polite">{priceLabel}</output>
                        <button
                          aria-label={t('Augmenter le prix démo')}
                          disabled={price >= 10000}
                          onClick={() => {
                            setPrice((p) => p + 50);
                            setPublished(false);
                          }}
                        >
                          <Plus size={16} />
                        </button>
                      </div>
                    </div>
                    <button className="button button-blue" onClick={() => setPublished(true)}>
                      {published ? (
                        <>
                          <Check size={16} />
                          {t('Aperçu mis à jour')}
                        </>
                      ) : (
                        <>
                          {t('Publier dans la démo')}
                          <ArrowRight size={16} />
                        </>
                      )}
                    </button>
                  </div>
                </div>
              )}
              {chapter === 2 && (
                <div className="story-sharing">
                  <div className="story-qr">
                    <img
                      src={qr}
                      width="128"
                      height="128"
                      alt={t('QR ouvrant le menu de démonstration DishPlay')}
                    />
                    <span>{t('Scannez. Découvrez.')}</span>
                  </div>
                  <div className="story-menu">
                    <div className="story-stage-top">
                      <span>dishplay.</span>
                      <ScanLine size={18} />
                    </div>
                    <img
                      src="/images/burger.jpg"
                      width="500"
                      height="420"
                      alt={t('Un burger photographié, exemple de présentation d’un plat')}
                      loading="lazy"
                    />
                    <div>
                      <span className="eyebrow">{t('LE MENU À PORTÉE DE MAIN')}</span>
                      <h4>{t('Atelier des saveurs')}</h4>
                      <p>{t('Des plats à découvrir, à votre rythme.')}</p>
                      <Link href="/menu/demo" className="inline-link">
                        {t('Ouvrir ce menu démo')}
                        <ArrowRight size={17} />
                      </Link>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
          <div className="story-scroll-progress" aria-hidden="true">
            <span />
          </div>
        </div>
      </div>
    </section>
  );
}
