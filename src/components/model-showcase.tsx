'use client';

import { useEffect, useRef, useState } from 'react';
import type { ModelViewerElement } from '@google/model-viewer';
import { ArrowUpRight, Box, Move, Pause, Play, RotateCcw } from 'lucide-react';
import { LocalizedLink as Link, useI18n } from './language';

const VIEWS = [
  { label: 'Vue de face', orbit: '0deg 75deg 110%' },
  { label: 'Vue de côté', orbit: '65deg 75deg 110%' },
  { label: 'Vue du dessus', orbit: '0deg 25deg 110%' },
] as const;

export function ModelShowcase() {
  const { t } = useI18n();
  const stage = useRef<HTMLDivElement>(null);
  const mount = useRef<HTMLDivElement>(null);
  const viewer = useRef<ModelViewerElement | null>(null);
  const rotationWanted = useRef(false);
  const syncRotation = useRef<() => void>(() => {});
  const [active, setActive] = useState(false);
  const [status, setStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [progress, setProgress] = useState(0);
  const [rotating, setRotating] = useState(false);
  const [view, setView] = useState<number | null>(0);

  function rotate(enabled: boolean) {
    rotationWanted.current = enabled;
    setRotating(enabled);
    syncRotation.current();
  }

  function start() {
    setStatus('loading');
    setProgress(0);
    setView(0);
    rotate(!matchMedia('(prefers-reduced-motion: reduce)').matches);
    setActive(true);
  }

  useEffect(() => {
    if (!active || !mount.current || !stage.current) return;
    const container = mount.current;
    const controller = new AbortController();
    const { signal } = controller;
    const motion = matchMedia('(prefers-reduced-motion: reduce)');
    let element: ModelViewerElement | undefined;
    let visible = false;
    let cancelled = false;
    const sync = () => {
      if (element) element.autoRotate = rotationWanted.current && visible && !document.hidden;
    };
    syncRotation.current = sync;
    const stopRotation = () => {
      rotationWanted.current = false;
      setRotating(false);
      sync();
    };
    const fail = () => {
      if (cancelled) return;
      stopRotation();
      setStatus('error');
      setActive(false);
    };
    const timeout = window.setTimeout(fail, 30_000);
    const observer = new IntersectionObserver(
      ([entry]) => {
        visible = entry.isIntersecting;
        sync();
      },
      { threshold: 0.1 },
    );
    observer.observe(stage.current);
    document.addEventListener('visibilitychange', sync, { signal });
    motion.addEventListener(
      'change',
      () => {
        if (motion.matches) stopRotation();
      },
      { signal },
    );

    // Neither the engine nor the model is requested until the visitor presses Explore.
    void import('@google/model-viewer')
      .then(({ ModelViewerElement }) => {
        if (cancelled) return;
        ModelViewerElement.modelCacheSize = 1;
        element = document.createElement('model-viewer') as ModelViewerElement;
        viewer.current = element;
        element.addEventListener(
          'load',
          () => {
            clearTimeout(timeout);
            setStatus('ready');
            sync();
          },
          { signal },
        );
        element.addEventListener('error', fail, { signal });
        element.addEventListener(
          'progress',
          (event) => {
            const { totalProgress } = (event as unknown as CustomEvent<{ totalProgress: number }>)
              .detail;
            setProgress(Math.round(totalProgress * 100));
          },
          { signal },
        );
        element.addEventListener(
          'camera-change',
          (event) => {
            if ((event as CustomEvent<{ source: string }>).detail.source === 'user-interaction') {
              stopRotation();
              setView(null);
            }
          },
          { signal },
        );
        const attributes = {
          src: '/models/avocado-demo.glb',
          alt: t('Avocat en 3D. Utilisez les flèches du clavier ou faites glisser pour tourner.'),
          'camera-controls': '',
          'touch-action': 'pan-y',
          'camera-orbit': VIEWS[0].orbit,
          'min-camera-orbit': 'auto 15deg 85%',
          'max-camera-orbit': 'auto 150deg 180%',
          'field-of-view': '30deg',
          'shadow-intensity': '0.8',
          'interaction-prompt': 'none',
          'rotation-per-second': '12deg',
          'auto-rotate-delay': '0',
          loading: 'eager',
          reveal: 'auto',
        };
        for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
        container.append(element);
        sync();
      })
      .catch(fail);

    return () => {
      cancelled = true;
      clearTimeout(timeout);
      observer.disconnect();
      controller.abort();
      syncRotation.current = () => {};
      if (element) {
        element.autoRotate = false;
        element.remove();
      }
      viewer.current = null;
    };
  }, [active, t]);

  function changeView(index: number) {
    const element = viewer.current;
    if (!element) return;
    rotate(false);
    setView(index);
    element.resetTurntableRotation();
    element.cameraOrbit = VIEWS[index].orbit;
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) element.jumpCameraToGoal();
  }

  const ready = status === 'ready';
  return (
    <section
      className="model-showcase container"
      id="experience-3d"
      aria-labelledby="model-heading"
    >
      <div className="model-copy" data-reveal>
        <p className="eyebrow">{t('UNE AUTRE DIMENSION. POUR DE VRAI.')}</p>
        <h2 id="model-heading">
          {t('Tournez autour.')}
          <br />
          <span>{t('Approchez le détail.')}</span>
        </h2>
        <p>
          {t(
            'La texture, le relief, chaque angle. Explorez un vrai objet 3D, directement dans votre navigateur.',
          )}
        </p>
        <div className="model-features">
          <span>
            <Move size={18} />
            {t('Tournez du bout des doigts')}
          </span>
          <span>
            <Box size={18} />
            {t('Découvrez le volume')}
          </span>
        </div>
        <Link className="text-button" href="/menu/demo">
          {t('Explorer le menu démo')}
          <ArrowUpRight size={17} />
        </Link>
      </div>
      <div className="model-card">
        <div className="model-stage" ref={stage} data-status={status}>
          <span className="model-badge">
            <span className="tiny-dot" />
            {t('MODÈLE DE DÉMONSTRATION')}
          </span>
          <img
            className="model-poster"
            src="/images/avocado-3d.webp"
            width="800"
            height="800"
            loading="lazy"
            alt={t('Aperçu du modèle 3D d’un avocat')}
            hidden={ready}
          />
          <div className="model-canvas" ref={mount} hidden={!active} />
          {!ready && (
            <div className="model-launch">
              {status === 'loading' ? (
                <div className="model-loading" role="status">
                  <span>{t('Chargement de la 3D…')}</span>
                  <progress max="100" value={progress} aria-label={t('Chargement du modèle 3D')} />
                  <button
                    type="button"
                    className="text-button"
                    onClick={() => {
                      setActive(false);
                      setStatus('idle');
                    }}
                  >
                    {t('Annuler')}
                  </button>
                </div>
              ) : (
                <>
                  {status === 'error' && (
                    <p role="alert">
                      {t('La 3D n’a pas pu démarrer. Vous pouvez réessayer ou garder cet aperçu.')}
                    </p>
                  )}
                  <button type="button" className="button button-blue" onClick={start}>
                    <Box size={18} />
                    {t(status === 'error' ? 'Réessayer la 3D' : 'Explorer en 3D')}
                  </button>
                </>
              )}
            </div>
          )}
          {ready && (
            <p className="model-gesture">{t('Glissez pour tourner · Pincez pour zoomer')}</p>
          )}
        </div>
        {ready && (
          <div className="model-controls">
            <div className="model-views" role="group" aria-label={t('Angles de vue')}>
              {VIEWS.map((preset, index) => (
                <button
                  type="button"
                  key={preset.label}
                  aria-pressed={view === index}
                  onClick={() => changeView(index)}
                >
                  {t(preset.label)}
                </button>
              ))}
            </div>
            <div className="model-actions">
              <button type="button" onClick={() => rotate(!rotating)} aria-pressed={rotating}>
                {rotating ? <Pause size={16} /> : <Play size={16} />}
                {t(rotating ? 'Arrêter la rotation' : 'Lancer la rotation')}
              </button>
              <button
                type="button"
                onClick={() => {
                  setActive(false);
                  setStatus('idle');
                }}
              >
                <RotateCcw size={15} />
                {t('Revenir à l’image')}
              </button>
            </div>
          </div>
        )}
        <p className="model-credit">
          {t('Avocat · modèle de démonstration Microsoft (CC0).')}{' '}
          <a
            href="https://github.com/KhronosGroup/glTF-Sample-Assets/tree/main/Models/Avocado"
            target="_blank"
            rel="noreferrer"
          >
            {t('Source du modèle')}
          </a>
        </p>
      </div>
    </section>
  );
}
