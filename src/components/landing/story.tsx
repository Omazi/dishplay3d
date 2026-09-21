'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';
import type { ModelViewerElement } from '@google/model-viewer';
import { ArrowDown, Box, RotateCcw, MoveHorizontal } from 'lucide-react';
import { showcaseModels } from '@/lib/showcase-models';
import { chapterIds, chapters, motionQuery, narrativeFrame } from './motion';
import type { LandingCopy } from './content';

const model = showcaseModels[0];

export function LandingStory({
  children,
  phone,
  copy,
}: {
  children: ReactNode;
  phone: ReactNode;
  copy: LandingCopy;
}) {
  const root = useRef<HTMLDivElement>(null);
  const mount = useRef<HTMLDivElement>(null);
  const viewer = useRef<ModelViewerElement | null>(null);
  const progress = useRef(0);
  const interactive = useRef(false);
  const applyFrame = useRef<() => void>(() => {});
  const jump = useRef<(index: number) => void>(() => {});
  const [enhanced, setEnhanced] = useState(false);
  const [wanted, setWanted] = useState(false);
  const [visible, setVisible] = useState(true);
  const [active, setActive] = useState(false);
  const [scene, setScene] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [status, setStatus] = useState<'poster' | 'loading' | 'ready' | 'error'>('poster');
  const [arMessage, setArMessage] = useState('');

  function control(value: boolean) {
    interactive.current = value;
    setActive(value);
    if (viewer.current) {
      viewer.current.cameraControls = value;
      viewer.current.tabIndex = value ? 0 : -1;
      viewer.current.style.pointerEvents = value ? 'auto' : 'none';
    }
    if (!value) applyFrame.current();
  }

  useEffect(() => {
    const element = root.current!;
    if (!matchMedia(motionQuery).matches) element.dataset.enhanced = 'false';
    const abort = new AbortController();
    let dispose: (() => void) | undefined;
    let currentScene = 0;
    const stage = element.querySelector<HTMLElement>('.launch-stage')!;
    const scenes = [...element.querySelectorAll<HTMLElement>('.launch-scene')];
    const observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting));
    observer.observe(element);
    // GSAP owns scroll progression. CSS owns sticky layout; no scroll interception or pin spacers.
    void Promise.all([import('gsap'), import('gsap/ScrollTrigger')])
      .then(([{ gsap }, { ScrollTrigger }]) => {
        if (abort.signal.aborted) return;
        gsap.registerPlugin(ScrollTrigger);
        const media = gsap.matchMedia();
        media.add(motionQuery, () => {
          element.dataset.enhanced = 'true';
          setEnhanced(true);
          const paint = () => {
            const frame = narrativeFrame(progress.current, stage.clientWidth, stage.clientHeight);
            const values = {
              x: `${frame.x}px`,
              y: `${frame.y}px`,
              size: `${frame.size}px`,
              'render-size': `${frame.renderSize}px`,
              'dish-scale': String(frame.size / frame.renderSize),
              'phone-shell': String(frame.phoneShell),
              'phone-width': `${frame.phoneWidth}px`,
              'phone-y': `${frame.centerY}px`,
              phone: String(frame.phone),
              'contact-shadow': String(frame.table),
              table: String(frame.table),
              progress: String(frame.progress),
            };
            for (const [key, value] of Object.entries(values))
              stage.style.setProperty(`--${key}`, value);
            if (viewer.current && !interactive.current && !document.hidden) {
              viewer.current.cameraOrbit = `${frame.theta}deg ${frame.phi}deg ${frame.radius}%`;
              viewer.current.jumpCameraToGoal();
            }
            element.dataset.scene = String(frame.scene);
            scenes.forEach((section, index) => {
              section.style.opacity = String(frame.copyOpacity[index]);
              section.style.visibility = frame.copyOpacity[index] > 0 ? 'visible' : 'hidden';
              section.inert = index !== frame.scene;
              section.setAttribute('aria-hidden', String(index !== frame.scene));
            });
            if (currentScene !== frame.scene) {
              currentScene = frame.scene;
              setScene(frame.scene);
              setArMessage('');
            }
            if (frame.progress > 0.015) setWanted(true);
          };
          applyFrame.current = paint;
          const trigger = ScrollTrigger.create({
            trigger: element,
            start: 'top 64px',
            end: 'bottom bottom',
            onUpdate: (self) => {
              progress.current = self.progress;
              paint();
            },
            onRefresh: (self) => {
              progress.current = self.progress;
              paint();
            },
          });
          jump.current = (index) => {
            const top = trigger.start + chapters[index] * (trigger.end - trigger.start);
            window.scrollTo({ top, behavior: 'instant' });
            trigger.update();
          };
          const hash = () => {
            const index = chapterIds.indexOf(location.hash.slice(1) as (typeof chapterIds)[number]);
            if (index >= 0) jump.current(index);
          };
          const click = (event: MouseEvent) => {
            const anchor = (event.target as Element).closest<HTMLAnchorElement>('a[href^="#"]');
            const index = chapterIds.indexOf(anchor?.hash.slice(1) as (typeof chapterIds)[number]);
            if (index < 0 || event.ctrlKey || event.metaKey || event.shiftKey) return;
            event.preventDefault();
            history.pushState(null, '', `#${chapterIds[index]}`);
            jump.current(index);
            scenes[index].querySelector<HTMLElement>('h1, h2')?.focus({ preventScroll: true });
          };
          document.addEventListener('click', click);
          window.addEventListener('hashchange', hash);
          paint();
          hash();
          return () => {
            document.removeEventListener('click', click);
            window.removeEventListener('hashchange', hash);
            trigger.kill();
            element.dataset.enhanced = 'false';
            setEnhanced(false);
            setWanted(false);
            control(false);
            scenes.forEach((section) => {
              section.inert = false;
              section.removeAttribute('aria-hidden');
              section.removeAttribute('style');
            });
            applyFrame.current = () => {};
            stage.removeAttribute('style');
          };
        });
        dispose = () => media.revert();
      })
      .catch(() => {
        element.dataset.enhanced = 'false';
        setEnhanced(false);
      });
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && interactive.current) {
        control(false);
        element
          .querySelector<HTMLAnchorElement>('.launch-stage-bottom a[aria-current="step"]')
          ?.focus();
      }
    };
    document.addEventListener('keydown', escape, { signal: abort.signal });
    document.addEventListener(
      'visibilitychange',
      () => {
        if (!document.hidden) applyFrame.current();
      },
      { signal: abort.signal },
    );
    return () => {
      abort.abort();
      observer.disconnect();
      dispose?.();
    };
  }, []);

  // One viewer, one model. Release the element/renderer scene when the story leaves the viewport.
  useEffect(() => {
    if (!wanted || !visible || !mount.current) return;
    const host = mount.current;
    const abort = new AbortController();
    let element: ModelViewerElement | undefined;
    let failed = false;
    setStatus('loading');
    const fail = () => {
      if (abort.signal.aborted || failed) return;
      failed = true;
      clearTimeout(timeout);
      setStatus('error');
      element?.remove();
      viewer.current = null;
    };
    const timeout = window.setTimeout(fail, 25_000);
    // model-viewer can emit "load" after parsing a GLB even without a working
    // renderer. Check WebGL2 first so that success never replaces the poster
    // with an empty surface on unsupported/disabled graphics hardware.
    let graphics: WebGL2RenderingContext | null = null;
    try {
      graphics = document.createElement('canvas').getContext('webgl2');
    } catch {
      /* Browser policy may reject context creation. */
    }
    if (!graphics) {
      fail();
      return () => {
        abort.abort();
        clearTimeout(timeout);
      };
    }
    graphics.getExtension('WEBGL_lose_context')?.loseContext();
    void import('@google/model-viewer')
      .then(({ ModelViewerElement }) => {
        if (abort.signal.aborted || failed) return;
        ModelViewerElement.modelCacheSize = 1;
        ModelViewerElement.minimumRenderScale = 0.5;
        element = document.createElement('model-viewer') as ModelViewerElement;
        const attributes = {
          src: `${model.src}${attempt ? `?retry=${attempt}` : ''}`,
          alt: copy.poster,
          ar: '',
          'ios-src': model.usdz,
          'ar-modes': 'webxr scene-viewer quick-look',
          'ar-scale': 'auto',
          'disable-zoom': '',
          'disable-pan': '',
          'disable-tap': '',
          'touch-action': 'pan-y',
          'camera-orbit': model.orbit,
          'min-camera-orbit': 'auto 45deg 99%',
          'max-camera-orbit': 'auto 85deg 120%',
          'field-of-view': '30deg',
          'shadow-intensity': '.6',
          'shadow-softness': '1',
          exposure: '.9',
          'interaction-prompt': 'none',
          loading: 'eager',
        };
        for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
        const hiddenButton = document.createElement('span');
        hiddenButton.slot = 'ar-button';
        element.append(hiddenButton);
        element.cameraControls = interactive.current;
        element.tabIndex = interactive.current ? 0 : -1;
        element.style.pointerEvents = interactive.current ? 'auto' : 'none';
        const options = { signal: abort.signal };
        element.addEventListener(
          'load',
          () => {
            clearTimeout(timeout);
            if (!failed) {
              setStatus('ready');
              applyFrame.current();
            }
          },
          options,
        );
        element.addEventListener('error', fail, options);
        element.addEventListener(
          'ar-status',
          (event) => {
            if ((event as CustomEvent).detail.status === 'failed') setArMessage(copy.arError);
          },
          options,
        );
        viewer.current = element;
        host.append(element);
        // model-viewer reports context loss as an error; also listen to its canvas for browsers
        // that dispatch only webglcontextlost on the shared renderer surface.
        element.updateComplete.then(() =>
          element?.shadowRoot
            ?.querySelector('canvas')
            ?.addEventListener('webglcontextlost', fail, options),
        );
        applyFrame.current();
      })
      .catch(fail);
    return () => {
      abort.abort();
      clearTimeout(timeout);
      element?.remove();
      viewer.current = null;
      setStatus('poster');
    };
  }, [wanted, visible, attempt, copy]);

  async function ar() {
    const element = viewer.current;
    if (!element?.canActivateAR) {
      setArMessage(copy.arFallback);
      return;
    }
    control(false);
    try {
      await element.activateAR();
    } catch {
      setArMessage(copy.arError);
    }
  }

  return (
    <div
      className="launch-story"
      data-enhanced="true"
      ref={root}
      data-scene={scene}
      data-status={status}
      data-interactive={active}
    >
      <div className="launch-stage">
        <div className="launch-table" aria-hidden="true">
          <img
            src="/images/restaurant-table.webp"
            width="1440"
            height="960"
            alt=""
            loading="lazy"
          />
        </div>
        <div className="launch-phone" aria-hidden="true">
          {phone}
        </div>
        <div className="launch-shared-dish">
          <img
            className="launch-poster"
            aria-hidden={status === 'ready'}
            src="/images/burger-story.webp"
            width="700"
            height="700"
            alt={copy.poster}
            fetchPriority="high"
            decoding="async"
          />
          <div className="launch-model" ref={mount} aria-hidden={status !== 'ready'} />
        </div>
        <div
          className="launch-scenes"
          onClick={(event) => {
            const button = (event.target as Element).closest<HTMLElement>('[data-explore]');
            if (button) {
              setWanted(true);
              control(true);
            }
          }}
        >
          {children}
        </div>
        <div
          className="launch-tools"
          data-show={enhanced ? scene === 1 || scene === 3 || active || status === 'error' : wanted}
        >
          {status === 'loading' && <p role="status">{copy.loading}</p>}
          {status === 'error' && (
            <p role="alert">
              {copy.error}{' '}
              <button
                onClick={() => {
                  setWanted(true);
                  setAttempt((value) => value + 1);
                }}
              >
                {copy.retry}
              </button>
            </p>
          )}
          {status === 'ready' && (
            <div className="launch-tool-buttons">
              <button
                className="launch-control"
                aria-pressed={active}
                onClick={() => control(!active)}
              >
                {active ? <RotateCcw size={16} /> : <MoveHorizontal size={16} />}
                {active ? copy.back : copy.explore}
              </button>
              {(scene === 3 || !enhanced) && (
                <button onClick={ar}>
                  <Box size={16} />
                  {copy.ar}
                </button>
              )}
            </div>
          )}
          {active && status === 'ready' && <p className="launch-control-hint">{copy.controls}</p>}
          {arMessage && (
            <p role="status" className="launch-ar-message">
              {arMessage}
            </p>
          )}
        </div>
        <div className="launch-stage-bottom">
          <span className="launch-scroll-hint">
            <ArrowDown size={13} />
            {copy.scroll}
          </span>
          <span className="launch-media-label">
            {scene === 3 ? copy.tableCaption : copy.illustrative}
          </span>
          <nav aria-label={copy.chaptersLabel}>
            {copy.chapterLabels.map((label, index) => (
              <a
                href={`#${chapterIds[index]}`}
                key={label}
                aria-current={scene === index ? 'step' : undefined}
              >
                <span>0{index + 1}</span>
                <span>{label}</span>
              </a>
            ))}
          </nav>
        </div>
      </div>
    </div>
  );
}
