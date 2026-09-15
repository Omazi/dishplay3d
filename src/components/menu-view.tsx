'use client';

import { createElement, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import {
  ArrowLeft,
  ArrowUpRight,
  Box,
  Camera,
  Check,
  ImageIcon,
  LoaderCircle,
  X,
} from 'lucide-react';
import type { Dish, PublicMenu } from '@/lib/contracts';
import { dishImageUrl } from '@/lib/demo';
import { formatPrice } from './api-client';
import { Brand } from './brand';

function ModelView({ dish }: { dish: Dish }) {
  const [ready, setReady] = useState(false);
  const [error, setError] = useState('');
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let alive = true;
    import('@google/model-viewer')
      .then(() => {
        if (alive) setReady(true);
      })
      .catch(() => {
        if (alive) setError('La vue 3D n’a pas pu charger. Vous pouvez revenir à la photo.');
      });
    return () => {
      alive = false;
    };
  }, []);
  useEffect(() => {
    const viewer = container.current?.querySelector('model-viewer');
    if (!viewer) return;
    const onError = () =>
      setError('Le modèle est indisponible. Revenez à la photo ou réessayez plus tard.');
    viewer.addEventListener('error', onError);
    return () => viewer.removeEventListener('error', onError);
  }, [ready]);
  if (error)
    return (
      <div className="viewer-message" role="alert">
        <ImageIcon size={30} />
        <p>{error}</p>
      </div>
    );
  if (!ready)
    return (
      <div className="viewer-message" role="status">
        <LoaderCircle className="spin" size={28} />
        <p>Chargement de la visionneuse…</p>
      </div>
    );
  return (
    <div className="model-container" ref={container}>
      {createElement(
        'model-viewer',
        {
          src: dish.modelGlbUrl,
          'ios-src': dish.modelUsdzUrl || undefined,
          poster: dishImageUrl(dish) || undefined,
          alt: `Modèle 3D de ${dish.name}`,
          'camera-controls': true,
          'touch-action': 'pan-y',
          ar: true,
          'ar-modes': dish.modelUsdzUrl ? 'webxr scene-viewer quick-look' : 'webxr scene-viewer',
          'ar-scale': 'fixed',
          'shadow-intensity': '1',
          'interaction-prompt': 'auto',
          style: { width: '100%', height: '100%', minHeight: '320px' },
        },
        <button className="button button-blue ar-button" slot="ar-button">
          <Camera size={17} /> Voir sur ma table
        </button>,
      )}
      <p className="viewer-hint">Glissez pour tourner · Pincez pour zoomer</p>
    </div>
  );
}

export function MenuView({ menu, preview = false }: { menu: PublicMenu; preview?: boolean }) {
  const [category, setCategory] = useState('all');
  const [selected, setSelected] = useState<Dish | null>(null);
  const [mode, setMode] = useState<'photo' | '3d'>('photo');
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
            <span className="tiny-dot" /> Menu de démonstration · Photos et informations
            illustratives
          </span>
          <Link href="/signup">
            Créer ma carte <ArrowUpRight size={14} />
          </Link>
        </div>
      )}
      <header className="menu-nav container">
        <Brand />
        {!preview && (
          <Link href="/" className="subtle-link">
            <ArrowLeft size={15} /> À propos de DishPlay
          </Link>
        )}
      </header>
      <main id={preview ? undefined : 'main'} className="container menu-main">
        <div className="menu-intro">
          <p className="eyebrow">BONJOUR, INSTALLEZ-VOUS.</p>
          <h1>{menu.restaurant.name}</h1>
          <p>{menu.restaurant.tagline || 'De belles assiettes, à découvrir à votre rythme.'}</p>
          <div className="menu-intro-line">
            <span>
              <Check size={14} /> Notre carte, à portée de main
            </span>
            <span>Bon appétit.</span>
          </div>
        </div>
        <nav className="category-tabs" aria-label="Catégories du menu">
          <button aria-pressed={category === 'all'} onClick={() => setCategory('all')}>
            Toute la carte <span>{available.length}</span>
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
                  aria-label={`Découvrir ${dish.name}`}
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
                      <span>À découvrir à table</span>
                    </div>
                  )}
                  <span className="dish-photo-chip">
                    {dish.modelGlbUrl ? (
                      <>
                        <Box size={14} /> Explorer en 3D
                      </>
                    ) : (
                      <>
                        <ImageIcon size={14} /> Voir le plat
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
                      {formatPrice(dish.priceCents, menu.restaurant.currency)}
                    </strong>
                  </div>
                  <p>{dish.description}</p>
                  {dish.allergens.length > 0 && (
                    <span className="allergen-line">Allergènes : {dish.allergens.join(', ')}</span>
                  )}
                </div>
              </article>
            ))}
          </div>
        ) : (
          <div className="empty-state">
            <ImageIcon size={32} />
            <h2>La carte se prépare.</h2>
            <p>Aucun plat disponible dans cette catégorie pour le moment.</p>
          </div>
        )}
        <div className="menu-bottom-note">
          <span>Une question sur un ingrédient ?</span>
          <p>Notre équipe est là pour vous renseigner avant votre choix.</p>
        </div>
      </main>
      <footer className="menu-footer">
        <span>LE PLAISIR DE DÉCOUVRIR</span>
        <Brand />
        {menu.isDemo && (
          <small>Photographies d’illustration · Voir les crédits dans le dépôt.</small>
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
        <button className="dialog-close icon-button" onClick={close} aria-label="Fermer le plat">
          <X size={20} />
        </button>
        {selected && (
          <>
            <div className="dish-dialog-visual">
              {mode === '3d' && selected.modelGlbUrl ? (
                <ModelView dish={selected} />
              ) : dishImageUrl(selected) ? (
                <img src={dishImageUrl(selected)!} alt={selected.name} />
              ) : (
                <div className="no-photo">
                  <ImageIcon size={40} />
                </div>
              )}
            </div>
            <div className="dish-dialog-body">
              <div className="view-switch" aria-label="Vue du plat">
                <button aria-pressed={mode === 'photo'} onClick={() => setMode('photo')}>
                  <ImageIcon size={15} /> Photo
                </button>
                {selected.modelGlbUrl && (
                  <button aria-pressed={mode === '3d'} onClick={() => setMode('3d')}>
                    <Box size={15} /> 3D
                  </button>
                )}
              </div>
              <div className="dish-dialog-heading">
                <h2>{selected.name}</h2>
                <strong>{formatPrice(selected.priceCents, menu.restaurant.currency)}</strong>
              </div>
              <p>{selected.description}</p>
              {selected.allergens.length > 0 && (
                <div className="allergen-box">
                  <strong>Allergènes déclarés</strong>
                  <p>{selected.allergens.join(' · ')}</p>
                </div>
              )}
              {!selected.modelGlbUrl && (
                <p className="field-hint">Ce plat est présenté en photographie.</p>
              )}
            </div>
          </>
        )}
      </dialog>
    </div>
  );
}
