'use client';

import { useEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowUpRight, Move, RotateCcw, Sparkles, X, ZoomIn } from 'lucide-react';
import { LocalizedLink as Link, useI18n } from './language';
import type { PhotoScene } from '@/lib/photo-scene';
import { showcaseModels } from '@/lib/showcase-models';
import { DishModel } from './dish-model';

const photos = [
  {
    id: 'burger',
    name: 'Le burger de l’atelier',
    short: 'Le burger',
    title: 'L’envie. Au premier regard.',
    text: 'Le pain doré. Les textures. Les détails qui donnent envie de choisir.',
    image: '/images/burger.jpg',
    alt: 'Un burger photographié, exemple de présentation d’un plat',
    number: '01',
  },
  {
    id: 'pasta',
    name: 'Pasta della casa',
    short: 'Les pâtes',
    title: 'Le détail fait la différence.',
    text: 'Un dressage, une lumière, votre signature. Votre cuisine prend toute sa place.',
    image: '/images/pasta.jpg',
    alt: 'Photographie illustrative d’un plat de pâtes',
    number: '02',
  },
  {
    id: 'salad',
    name: 'La salade du marché',
    short: 'La salade',
    title: 'Toute la fraîcheur. À l’écran.',
    text: 'Des couleurs franches. Des ingrédients visibles. Une carte qui se découvre avec les yeux.',
    image: '/images/salad.jpg',
    alt: 'Une salade, photographie d’illustration',
    number: '03',
  },
] as const;

export function PhotoGallery() {
  const { t } = useI18n();
  const gallery = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const root = gallery.current;
    if (!root) return;
    const media = matchMedia('(prefers-reduced-motion: reduce)');
    let frame = 0;
    const reset = () =>
      root.querySelectorAll<HTMLElement>('figure').forEach((card) => {
        card.style.removeProperty('--tilt-x');
        card.style.removeProperty('--tilt-y');
      });
    const move = (event: PointerEvent) => {
      if (media.matches || event.pointerType !== 'mouse') return;
      const card = (event.target as HTMLElement).closest('figure');
      if (!card || !root.contains(card)) return;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const box = card.getBoundingClientRect();
        card.style.setProperty(
          '--tilt-x',
          `${(-(event.clientY - box.top - box.height / 2) / box.height) * 7}deg`,
        );
        card.style.setProperty(
          '--tilt-y',
          `${((event.clientX - box.left - box.width / 2) / box.width) * 9}deg`,
        );
      });
    };
    root.addEventListener('pointermove', move, { passive: true });
    root.addEventListener('pointerleave', reset);
    media.addEventListener('change', reset);
    return () => {
      cancelAnimationFrame(frame);
      root.removeEventListener('pointermove', move);
      root.removeEventListener('pointerleave', reset);
      media.removeEventListener('change', reset);
    };
  }, []);
  return (
    <div
      className="premium-food-gallery"
      ref={gallery}
      aria-label={t('Photographies de présentation')}
    >
      {[2, 0, 1].map((index) => {
        const photo = photos[index];
        return (
          <figure
            key={photo.id}
            className={
              index === 0 ? 'food-main' : `food-side food-${index === 2 ? 'left' : 'right'}`
            }
          >
            <a
              className="food-visual"
              href="#experience-3d"
              aria-label={t('Explorer {0} en relief', [t(photo.short)])}
              onClick={() =>
                window.dispatchEvent(new CustomEvent('dishplay:photo', { detail: index }))
              }
            >
              <img
                src={photo.image}
                width="1200"
                height={index === 0 ? '997' : index === 1 ? '877' : '800'}
                fetchPriority={index === 0 ? 'high' : undefined}
                alt={t(photo.alt)}
              />
              <figcaption>
                <span>
                  {photo.number} / {t(photo.short)}
                </span>
                {index === 0 && <strong>{t('L’envie se voit.')}</strong>}
                <span className="food-explore">
                  {t('Explorer le relief')}
                  <ArrowUpRight size={16} />
                </span>
              </figcaption>
            </a>
          </figure>
        );
      })}
    </div>
  );
}

export function PhotoShowcase() {
  const { t } = useI18n();
  const [selected, setSelected] = useState(0);
  const [mode, setMode] = useState<'photo' | 'model'>('photo');
  const [active, setActive] = useState(false);
  const [status, setStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [angle, setAngle] = useState(0);
  const [zoom, setZoom] = useState(false);
  const track = useRef<HTMLDivElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const scene = useRef<PhotoScene | null>(null);
  const photo = photos[selected];
  const photoId = photo.id;
  const imageUrl = photo.image;
  const select = (index: number) => {
    setSelected(index);
    setActive(false);
    setStatus('idle');
    setAngle(0);
    setZoom(false);
  };

  useEffect(() => {
    const choose = (event: Event) => {
      const index = (event as CustomEvent<unknown>).detail;
      if (
        typeof index === 'number' &&
        Number.isInteger(index) &&
        index >= 0 &&
        index < photos.length
      ) {
        select(index);
        setMode('photo');
      }
    };
    window.addEventListener('dishplay:photo', choose);
    return () => window.removeEventListener('dishplay:photo', choose);
  }, []);

  useEffect(() => {
    const root = track.current;
    if (!root) return;
    const media = matchMedia('(prefers-reduced-motion: reduce)');
    let frame = 0;
    const update = () => {
      frame = 0;
      const box = root.getBoundingClientRect();
      const progress = Math.max(
        0,
        Math.min(1, (innerHeight - box.top) / (innerHeight + box.height)),
      );
      root.style.setProperty('--photo-progress', media.matches ? '.5' : String(progress));
      scene.current?.resize();
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    window.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', schedule);
    document.addEventListener('visibilitychange', schedule);
    media.addEventListener('change', schedule);
    schedule();
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('scroll', schedule);
      window.removeEventListener('resize', schedule);
      document.removeEventListener('visibilitychange', schedule);
      media.removeEventListener('change', schedule);
    };
  }, []);

  useEffect(() => {
    if (!active || !canvas.current) return;
    const surface = canvas.current;
    const controller = new AbortController();
    const fail = () => {
      if (controller.signal.aborted) return;
      setStatus('error');
      setActive(false);
    };
    const timer = setTimeout(fail, 20_000);
    const observer = new ResizeObserver(() => scene.current?.resize());
    observer.observe(surface);
    void import('@/lib/photo-scene')
      .then(({ createPhotoScene }) => {
        if (controller.signal.aborted) return null;
        return createPhotoScene(surface, imageUrl, fail, controller.signal);
      })
      .then((result) => {
        if (!result || controller.signal.aborted) {
          result?.dispose();
          return;
        }
        clearTimeout(timer);
        scene.current = result;
        setStatus('ready');
      })
      .catch(() => {
        if (!controller.signal.aborted) fail();
      });
    return () => {
      clearTimeout(timer);
      controller.abort();
      observer.disconnect();
      scene.current?.dispose();
      scene.current = null;
    };
  }, [active, imageUrl]);

  function move(x: number, y: number) {
    scene.current?.move(x, y, zoom ? 1.22 : 1);
    if (stage.current) {
      stage.current.style.setProperty('--photo-x', `${x * 2.5}deg`);
      stage.current.style.setProperty('--photo-y', `${-y * 2}deg`);
    }
  }
  function reset() {
    setAngle(0);
    setZoom(false);
    scene.current?.move(0, 0, 1);
    stage.current?.style.setProperty('--photo-x', '0deg');
    stage.current?.style.setProperty('--photo-y', '0deg');
  }

  return (
    <section
      className="photo-experience"
      id="experience-3d"
      aria-labelledby="photo-heading"
      ref={track}
    >
      <div className="photo-intro container" data-reveal>
        <p className="eyebrow">{t('VOTRE CUISINE, AU PREMIER PLAN')}</p>
        <h2 id="photo-heading">
          {t('Une carte.')}
          <br />
          <span>{t('Qui prend vie.')}</span>
        </h2>
        <p>
          {t(
            'Trois plats. Trois univers. Approchez, changez de perspective et laissez parler les détails.',
          )}
        </p>
      </div>
      <div className="photo-theatre container">
        <div className="photo-selector" role="group" aria-label={t('Choisir un plat à explorer')}>
          {photos.map((item, index) => (
            <button
              key={item.id}
              type="button"
              aria-pressed={selected === index}
              onClick={() => {
                select(index);
                reset();
              }}
            >
              <span>{item.number}</span>
              {t(item.short)}
            </button>
          ))}
        </div>
        <div className="photo-modes" role="group" aria-label={t('Mode de présentation')}>
          <button
            type="button"
            aria-pressed={mode === 'photo'}
            onClick={() => {
              setMode('photo');
              reset();
            }}
          >
            {t('Photo en relief')}
          </button>
          <button
            type="button"
            aria-pressed={mode === 'model'}
            onClick={() => {
              setActive(false);
              setStatus('idle');
              setMode('model');
            }}
          >
            {t('Vue à 360°')}
          </button>
        </div>
        <div className="photo-editorial">
          <div className="photo-caption" aria-live="polite">
            <span className="photo-number">{photo.number} / 03</span>
            <h3>{t(photo.title)}</h3>
            <p>{t(photo.text)}</p>
            <Link className="text-button" href="/menu/demo">
              {t('Découvrir la carte')}
              <ArrowUpRight size={17} />
            </Link>
          </div>
          {mode === 'model' ? (
            <DishModel key={photo.id} model={showcaseModels[selected]} />
          ) : (
            <div className="photo-perspective">
              <div
                className="photo-scene"
                ref={stage}
                data-photo={photoId}
                data-status={status}
                onPointerMove={(event) => {
                  if (
                    status !== 'ready' ||
                    event.pointerType === 'touch' ||
                    matchMedia('(prefers-reduced-motion: reduce)').matches
                  )
                    return;
                  const box = event.currentTarget.getBoundingClientRect();
                  move(
                    ((event.clientX - box.left) / box.width) * 2 - 1,
                    1 - ((event.clientY - box.top) / box.height) * 2,
                  );
                }}
                onPointerLeave={() => {
                  move(angle / 100, 0);
                }}
              >
                <img
                  className="photo-source"
                  src={photo.image}
                  alt={t(photo.alt)}
                  width="1200"
                  height="997"
                  loading="lazy"
                />
                {active && (
                  <canvas
                    key={photoId}
                    ref={canvas}
                    className="photo-render"
                    aria-hidden="true"
                    hidden={status !== 'ready'}
                  />
                )}
                <div className="photo-surface-label">
                  <span>{t(photo.name)}</span>
                  <span>{t('PHOTO EN RELIEF')}</span>
                </div>
                {status !== 'ready' && (
                  <div className="photo-start">
                    {status === 'loading' ? (
                      <>
                        <span role="status">{t('Préparation du relief…')}</span>
                        <button
                          type="button"
                          aria-label={t('Annuler')}
                          onClick={() => {
                            setActive(false);
                            setStatus('idle');
                          }}
                        >
                          <X size={18} />
                        </button>
                      </>
                    ) : (
                      <button
                        type="button"
                        onClick={() => {
                          reset();
                          setStatus('loading');
                          setActive(true);
                        }}
                      >
                        <Move size={18} />
                        {t(status === 'error' ? 'Réessayer le relief' : 'Explorer cette photo')}
                        <ArrowUpRight size={17} />
                      </button>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
        {status === 'error' && (
          <p className="photo-feedback" role="alert">
            {t('Le relief n’est pas disponible pour le moment. La photo reste visible.')}
          </p>
        )}
        {status === 'ready' && (
          <div className="photo-tools">
            <label>
              <Move size={16} />
              <span>{t('Perspective')}</span>
              <input
                type="range"
                min="-100"
                max="100"
                value={angle}
                aria-label={t('Perspective de la photo')}
                onChange={(event) => {
                  const next = Number(event.target.value);
                  setAngle(next);
                  move(next / 100, 0);
                }}
              />
            </label>
            <button
              type="button"
              aria-pressed={zoom}
              onClick={() => {
                setZoom(!zoom);
                scene.current?.move(angle / 100, 0, zoom ? 1 : 1.22);
              }}
            >
              <ZoomIn size={16} />
              {t('Détails')}
            </button>
            <button type="button" onClick={reset} aria-label={t('Réinitialiser la perspective')}>
              <RotateCcw size={16} />
            </button>
            <button
              type="button"
              onClick={() => {
                setActive(false);
                setStatus('idle');
                reset();
              }}
            >
              <X size={16} />
              {t('Fermer')}
            </button>
          </div>
        )}
        <p className="photo-note">
          {t(
            mode === 'photo'
              ? 'Effet de relief à partir des photographies originales.'
              : 'Modèles 3D illustratifs de plats similaires, distincts des photographies.',
          )}
        </p>
      </div>
      <div className="photo-outro container" data-reveal>
        <Sparkles size={22} />
        <p>
          {t('Le soin que vous mettez dans vos plats.')}
          <br />
          <span>{t('Enfin, dans votre carte.')}</span>
        </p>
        <a href="#comment-ca-marche" aria-label={t('Voir comment ça marche')}>
          <ArrowDown size={24} />
        </a>
      </div>
    </section>
  );
}
