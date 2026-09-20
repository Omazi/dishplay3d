'use client';
import { useEffect, useRef, useState } from 'react';
import type { ModelViewerElement } from '@google/model-viewer';
import { Pause, Play, RotateCcw } from 'lucide-react';
import { useI18n } from './language';
import type { ShowcaseModel } from '@/lib/showcase-models';
import { ModelActions } from './model-actions';

export function DishModel({ model }: { model: ShowcaseModel }) {
  const { t } = useI18n();
  const mount = useRef<HTMLDivElement>(null);
  const viewer = useRef<ModelViewerElement | null>(null);
  const desired = useRef(false);
  const sync = useRef<() => void>(() => {});
  const [attempt, setAttempt] = useState(0);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [rotating, setRotating] = useState(false);
  function rotate(value: boolean) {
    desired.current = value;
    setRotating(value);
    sync.current();
  }
  useEffect(() => {
    if (!mount.current) return;
    const container = mount.current;
    const controller = new AbortController();
    const { signal } = controller;
    const motion = matchMedia('(prefers-reduced-motion: reduce)');
    let element: ModelViewerElement | undefined;
    let visible = false;
    let failed = false;
    const stop = () => {
      desired.current = false;
      setRotating(false);
      sync.current();
    };
    const fail = () => {
      if (!signal.aborted && !failed) {
        failed = true;
        clearTimeout(timer);
        stop();
        setStatus('error');
        element?.remove();
      }
    };
    const timer = setTimeout(fail, 30_000);
    const apply = () => {
      if (element) element.autoRotate = desired.current && visible && !document.hidden;
    };
    sync.current = apply;
    const observer = new IntersectionObserver(
      ([entry]) => {
        visible = entry.isIntersecting;
        apply();
      },
      { threshold: 0.1 },
    );
    observer.observe(container);
    document.addEventListener('visibilitychange', apply, { signal });
    motion.addEventListener(
      'change',
      () => {
        if (motion.matches) stop();
      },
      { signal },
    );
    void import('@google/model-viewer')
      .then(({ ModelViewerElement }) => {
        if (signal.aborted || failed) return;
        ModelViewerElement.modelCacheSize = 1;
        element = document.createElement('model-viewer') as ModelViewerElement;
        viewer.current = element;
        element.addEventListener(
          'load',
          () => {
            if (signal.aborted || failed) return;
            clearTimeout(timer);
            setStatus('ready');
            desired.current = !motion.matches;
            setRotating(desired.current);
            apply();
          },
          { signal },
        );
        element.addEventListener('error', fail, { signal });
        element.addEventListener(
          'camera-change',
          (event) => {
            if ((event as CustomEvent<{ source: string }>).detail.source === 'user-interaction')
              stop();
          },
          { signal },
        );
        const attributes = {
          src: `${model.src}${attempt ? `?retry=${attempt}` : ''}`,
          alt: t('Modèle illustratif à 360° : {0}', [t(model.name)]),
          ar: '',
          'ios-src': model.usdz,
          'ar-modes': 'webxr scene-viewer quick-look',
          'ar-scale': 'auto',
          'disable-zoom': '',
          'disable-pan': '',
          'disable-tap': '',
          'touch-action': 'pan-y',
          'camera-orbit': model.orbit,
          'min-camera-orbit': 'auto 10deg 65%',
          'max-camera-orbit': 'auto 170deg 170%',
          'field-of-view': '30deg',
          'shadow-intensity': '.7',
          'interaction-prompt': 'none',
          'rotation-per-second': '10deg',
          'auto-rotate-delay': '0',
          loading: 'eager',
          reveal: 'auto',
        };
        for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
        // The accessible AR action lives outside the gesture surface.
        const nativeButton = document.createElement('span');
        nativeButton.slot = 'ar-button';
        element.append(nativeButton);
        element.style.pointerEvents = 'none';
        container.append(element);
      })
      .catch(fail);
    return () => {
      clearTimeout(timer);
      observer.disconnect();
      controller.abort();
      sync.current = () => {};
      if (element) {
        element.autoRotate = false;
        element.remove();
      }
      viewer.current = null;
    };
  }, [model, attempt, t]);
  return (
    <div className="dish-model" data-status={status} data-model={model.id}>
      <div className="dish-model-stage">
        {status !== 'ready' && (
          <img
            src={model.poster}
            alt={t('Aperçu du modèle illustratif : {0}', [t(model.name)])}
            width="700"
            height="700"
          />
        )}
        <div className="dish-model-canvas" ref={mount} />
        <span className="dish-model-label">{t('MODÈLE 3D ILLUSTRATIF')}</span>
        {status === 'loading' && (
          <p className="dish-model-status" role="status">
            {t('Chargement de la 3D…')}
          </p>
        )}
        {status === 'error' && (
          <div className="dish-model-error">
            <p role="alert">
              {t('La 3D n’a pas pu démarrer. Vous pouvez réessayer ou garder cet aperçu.')}
            </p>
            <button
              type="button"
              onClick={() => {
                setStatus('loading');
                setAttempt((v) => v + 1);
              }}
            >
              {t('Réessayer la 3D')}
            </button>
          </div>
        )}
        {status === 'ready' && viewer.current && (
          <ModelActions viewer={viewer.current} onInteract={() => rotate(false)} />
        )}
      </div>
      {status === 'ready' && (
        <div className="dish-model-tools">
          <button type="button" onClick={() => rotate(!rotating)} aria-pressed={rotating}>
            {rotating ? <Pause size={16} /> : <Play size={16} />}
            {t(rotating ? 'Arrêter la rotation' : 'Lancer la rotation')}
          </button>
          <button
            type="button"
            onClick={() => {
              rotate(false);
              if (viewer.current) {
                viewer.current.resetTurntableRotation();
                viewer.current.cameraOrbit = model.orbit;
                if (matchMedia('(prefers-reduced-motion: reduce)').matches)
                  viewer.current.jumpCameraToGoal();
              }
            }}
          >
            <RotateCcw size={16} />
            {t('Vue initiale')}
          </button>
        </div>
      )}
      <p className="dish-model-credit">
        {t('Illustration · taille indicative en AR')}
        <br />
        <a href={model.source} target="_blank" rel="noreferrer">
          {model.author}
        </a>{' '}
        ·{' '}
        <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noreferrer">
          CC BY 4.0
        </a>
      </p>
    </div>
  );
}
