'use client';
import { useI18n, LanguageSwitcher } from '@/components/language';

import { createElement, useEffect, useRef, useState } from 'react';
import { LocalizedLink as Link } from '@/components/language';
import { ArrowLeft, ArrowUpRight, Box, Check, ImageIcon, LoaderCircle, X } from 'lucide-react';
import type { ModelViewerElement } from '@google/model-viewer';
import { ModelActions } from './model-actions';
import type { Dish, PublicMenu } from '@/lib/contracts';
import { showcaseModels, type ShowcaseModel } from '@/lib/showcase-models';
import { dishImageUrl, localizedDemoMenu } from '@/lib/demo';
import { formatPrice } from './api-client';
import { Brand } from './brand';

function ModelView({ dish, illustration }: { dish: Dish; illustration?: ShowcaseModel }) {
  const { t } = useI18n();
  const [ready, setReady] = useState(false);
  const [error, setError] = useState('');
  const [loadedViewer, setLoadedViewer] = useState<ModelViewerElement | null>(null);
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let alive = true;
    import('@google/model-viewer')
      .then(() => {
        if (alive) setReady(true);
      })
      .catch(() => {
        if (alive) setError(t('La vue 3D n’a pas pu charger. Vous pouvez revenir à la photo.'));
      });
    return () => {
      alive = false;
    };
  }, [t]);
  useEffect(() => {
    const viewer = container.current?.querySelector<ModelViewerElement>('model-viewer');
    if (!viewer) return;
    const onError = () =>
      setError(t('Le modèle est indisponible. Revenez à la photo ou réessayez plus tard.'));
    const onLoad = () => setLoadedViewer(viewer);
    viewer.addEventListener('error', onError);
    viewer.addEventListener('load', onLoad);
    if (viewer.loaded) onLoad();
    return () => {
      viewer.removeEventListener('error', onError);
      viewer.removeEventListener('load', onLoad);
    };
  }, [ready, t]);
  if (error)
    return (
      <div className="viewer-message" role="alert">
        <ImageIcon size={30} />
        <p>{t(error)}</p>
      </div>
    );
  if (!ready)
    return (
      <div className="viewer-message" role="status">
        <LoaderCircle className="spin" size={28} />
        <p>{t('Chargement de la visionneuse…')}</p>
      </div>
    );
  return (
    <div className="model-container" ref={container}>
      {createElement(
        'model-viewer',
        {
          src: dish.modelGlbUrl,
          'ios-src': illustration?.usdz ?? dish.modelUsdzUrl ?? undefined,
          poster: illustration?.poster ?? dishImageUrl(dish) ?? undefined,
          'camera-orbit': illustration?.orbit,
          alt: t('Modèle 3D de {0}', [dish.name]),
          'disable-zoom': true,
          'disable-pan': true,
          'disable-tap': true,
          'touch-action': 'pan-y',
          ar: true,
          'ar-modes': 'webxr scene-viewer quick-look',
          'ar-scale': illustration ? 'auto' : 'fixed',
          'shadow-intensity': '1',
          'interaction-prompt': 'none',
          style: { width: '100%', height: 'calc(100% - 110px)', pointerEvents: 'none' },
        },
        <span slot="ar-button" />,
      )}
      {loadedViewer && <ModelActions viewer={loadedViewer} />}
      {!loadedViewer && (
        <p className="viewer-hint" role="status">
          {t('Chargement de la 3D…')}
        </p>
      )}
    </div>
  );
}

export function MenuView({ menu, preview = false }: { menu: PublicMenu; preview?: boolean }) {
  const { t, locale, numberLocale } = useI18n();
  if (menu.isDemo) menu = localizedDemoMenu(locale);
  const [category, setCategory] = useState('all');
  const [selected, setSelected] = useState<Dish | null>(null);
  const [mode, setMode] = useState<'photo' | '3d'>('photo');
  const illustration = menu.isDemo
    ? showcaseModels.find((item) => selected?.imageId === `demo-${item.id}`)
    : undefined;
  const dialog = useRef<HTMLDialogElement>(null);
  const openButton = useRef<HTMLButtonElement | null>(null);
  const available = menu.dishes
    .filter((dish) => dish.isAvailable)
    .sort((a, b) => a.sortOrder - b.sortOrder);
  const visible =
    category === 'all' ? available : available.filter((dish) => dish.categoryId === category);
  function open(dish: Dish, button: HTMLButtonElement) {
    openButton.current = button;
    setSelected(dish);
    setMode('photo');
    dialog.current?.showModal();
  }
  function close() {
    dialog.current?.close();
    setSelected(null);
    setMode('photo');
    openButton.current?.focus();
  }
  return (
    <div className={`public-menu ${preview ? 'preview-menu' : ''}`}>
      {menu.isDemo && (
        <div className="demo-banner">
          <span>
            <span className="tiny-dot" />{' '}
            {t('Menu de démonstration · Photos et informations illustratives')}{' '}
          </span>
          <Link href="/signup">
            {' '}
            {t('Créer ma carte')} <ArrowUpRight size={14} />
          </Link>
        </div>
      )}
      <header className="menu-nav container">
        <Brand />
        {!preview && <LanguageSwitcher />}
        {!preview && (
          <Link href="/" className="subtle-link">
            <ArrowLeft size={15} /> {t('À propos de DishPlay')}{' '}
          </Link>
        )}
      </header>
      <main id={preview ? undefined : 'main'} className="container menu-main">
        <div className="menu-intro">
          <p className="eyebrow">{t('BONJOUR, INSTALLEZ-VOUS.')}</p>
          <h1>{menu.restaurant.name}</h1>
          <p>{menu.restaurant.tagline || t('De belles assiettes, à découvrir à votre rythme.')}</p>
          <div className="menu-intro-line">
            <span>
              <Check size={14} /> {t('Notre carte, à portée de main')}{' '}
            </span>
            <span>{t('Bon appétit.')}</span>
          </div>
        </div>
        <nav className="category-tabs" aria-label={t('Catégories du menu')}>
          <button aria-pressed={category === 'all'} onClick={() => setCategory('all')}>
            {' '}
            {t('Toute la carte')} <span>{available.length}</span>
          </button>
          {menu.categories
            .toSorted((a, b) => a.sortOrder - b.sortOrder)
            .map((item) => (
              <button
                key={item.id}
                onClick={() => setCategory(item.id)}
                aria-pressed={category === item.id}
              >
                {item.name}
              </button>
            ))}
        </nav>
        {visible.length ? (
          <div className="dishes-grid">
            {visible.map((dish, index) => (
              <article key={dish.id} className="dish-card">
                <button
                  className="dish-picture"
                  onClick={(event) => open(dish, event.currentTarget)}
                  aria-label={t('Découvrir {0}', [dish.name])}
                >
                  {dishImageUrl(dish) ? (
                    <img
                      src={dishImageUrl(dish)!}
                      alt={dish.name}
                      loading={index ? 'lazy' : 'eager'}
                      width="600"
                      height="480"
                    />
                  ) : (
                    <div className="no-photo">
                      <ImageIcon size={38} />
                      <span>{t('À découvrir à table')}</span>
                    </div>
                  )}
                  <span className="dish-photo-chip">
                    {dish.modelGlbUrl ? (
                      <>
                        <Box size={14} /> {t('Explorer en 3D')}{' '}
                      </>
                    ) : (
                      <>
                        <ImageIcon size={14} /> {t('Voir le plat')}{' '}
                      </>
                    )}
                  </span>
                </button>
                <div className="dish-info">
                  <div>
                    <h2>
                      <button onClick={(event) => open(dish, event.currentTarget)}>
                        {dish.name}
                      </button>
                    </h2>
                    <strong className="dish-price">
                      {formatPrice(dish.priceCents, menu.restaurant.currency, numberLocale)}
                    </strong>
                  </div>
                  <p>{dish.description}</p>
                  {dish.allergens.length > 0 && (
                    <span className="allergen-line">
                      {t('Allergènes :')} {dish.allergens.join(', ')}
                    </span>
                  )}
                </div>
              </article>
            ))}
          </div>
        ) : (
          <div className="empty-state">
            <ImageIcon size={32} />
            <h2>{t('La carte se prépare.')}</h2>
            <p>{t('Aucun plat disponible dans cette catégorie pour le moment.')}</p>
          </div>
        )}
        <div className="menu-bottom-note">
          <span>{t('Une question sur un ingrédient ?')}</span>
          <p>{t('Notre équipe est là pour vous renseigner avant votre choix.')}</p>
        </div>
      </main>
      <footer className="menu-footer">
        <span>{t('LE PLAISIR DE DÉCOUVRIR')}</span>
        <Brand />
        {menu.isDemo && (
          <small>{t('Photographies d’illustration · Voir les crédits dans le dépôt.')}</small>
        )}
      </footer>
      <dialog
        className="dish-dialog"
        ref={dialog}
        onCancel={close}
        onClick={(event) => {
          if (event.target === event.currentTarget) close();
        }}
      >
        <button
          className="dialog-close icon-button"
          onClick={close}
          aria-label={t('Fermer le plat')}
        >
          <X size={20} />
        </button>
        {selected && (
          <>
            <div className="dish-dialog-visual">
              {mode === '3d' && selected.modelGlbUrl ? (
                <ModelView dish={selected} illustration={illustration} />
              ) : dishImageUrl(selected) ? (
                <img src={dishImageUrl(selected)!} alt={selected.name} />
              ) : (
                <div className="no-photo">
                  <ImageIcon size={40} />
                </div>
              )}
            </div>
            <div className="dish-dialog-body">
              <div className="view-switch" aria-label={t('Vue du plat')}>
                <button aria-pressed={mode === 'photo'} onClick={() => setMode('photo')}>
                  <ImageIcon size={15} /> Photo
                </button>
                {selected.modelGlbUrl && (
                  <button aria-pressed={mode === '3d'} onClick={() => setMode('3d')}>
                    <Box size={15} /> 3D
                  </button>
                )}
              </div>
              {mode === '3d' && illustration && (
                <p className="field-hint">
                  {t('Modèle 3D illustratif d’un plat similaire, distinct de la photo.')}
                  <br />
                  {t('Illustration · taille indicative en AR')}
                  <br />
                  <a href={illustration.source} target="_blank" rel="noreferrer">
                    {illustration.author}
                  </a>{' '}
                  ·{' '}
                  <a
                    href="https://creativecommons.org/licenses/by/4.0/"
                    target="_blank"
                    rel="noreferrer"
                  >
                    CC BY 4.0
                  </a>
                </p>
              )}
              <div className="dish-dialog-heading">
                <h2>{selected.name}</h2>
                <strong>
                  {formatPrice(selected.priceCents, menu.restaurant.currency, numberLocale)}
                </strong>
              </div>
              <p>{selected.description}</p>
              {selected.allergens.length > 0 && (
                <div className="allergen-box">
                  <strong>{t('Allergènes déclarés')}</strong>
                  <p>{selected.allergens.join(' · ')}</p>
                </div>
              )}
              {!selected.modelGlbUrl && (
                <p className="field-hint">{t('Ce plat est présenté en photographie.')}</p>
              )}
            </div>
          </>
        )}
      </dialog>
    </div>
  );
}
