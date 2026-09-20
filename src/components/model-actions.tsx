'use client';

import { useEffect, useState } from 'react';
import type { ModelViewerElement } from '@google/model-viewer';
import { Camera, Check, Hand } from 'lucide-react';
import { useI18n } from './language';

/** Explicitly separate document gestures from model gestures. No global scroll lock. */
export function ModelActions({
  viewer,
  onInteract,
}: {
  viewer: ModelViewerElement;
  onInteract?: () => void;
}) {
  const { t } = useI18n();
  const [active, setActive] = useState(false);
  const [message, setMessage] = useState('');
  useEffect(() => {
    viewer.cameraControls = active;
    viewer.disableZoom = !active;
    viewer.disablePan = true;
    viewer.disableTap = true;
    viewer.touchAction = active ? 'none' : 'pan-y';
    viewer.style.pointerEvents = active ? 'auto' : 'none';
    const exit = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && active) {
        event.preventDefault();
        event.stopPropagation();
        setActive(false);
      }
    };
    // Capture Escape before a surrounding dish dialog dismisses itself.
    document.addEventListener('keydown', exit, true);
    return () => document.removeEventListener('keydown', exit, true);
  }, [active, viewer]);
  useEffect(() => {
    const fail = (event: Event) => {
      if ((event as CustomEvent<{ status: string }>).detail.status === 'failed')
        setMessage(
          'L’AR n’a pas démarré. Réessayez dans Safari sur iPhone ou Chrome sur Android compatible.',
        );
    };
    viewer.addEventListener('ar-status', fail);
    return () => viewer.removeEventListener('ar-status', fail);
  }, [viewer]);
  async function openAR() {
    setMessage('');
    setActive(false);
    onInteract?.();
    if (!viewer.canActivateAR) {
      setMessage(
        'Pour voir ce plat sur votre table, ouvrez cette page dans Safari sur iPhone ou Chrome sur Android compatible.',
      );
      return;
    }
    try {
      await viewer.activateAR();
    } catch {
      setMessage(
        'L’AR n’a pas démarré. Réessayez dans Safari sur iPhone ou Chrome sur Android compatible.',
      );
    }
  }
  return (
    <div className="model-interaction" data-active={active}>
      <p className="model-interaction-hint" aria-live="polite">
        {t(
          active
            ? 'Glissez pour tourner · Pincez pour zoomer'
            : 'Faites défiler librement. Activez la 3D pour manipuler le plat.',
        )}
      </p>
      <div className="model-interaction-buttons">
        <button
          type="button"
          aria-pressed={active}
          onClick={() => {
            onInteract?.();
            setMessage('');
            setActive(!active);
          }}
        >
          {active ? <Check size={16} /> : <Hand size={16} />}
          {t(active ? 'Terminer' : 'Manipuler en 3D')}
        </button>
        <button type="button" onClick={() => void openAR()}>
          <Camera size={16} />
          {t('Voir sur ma table')}
        </button>
      </div>
      {message && (
        <p className="model-ar-message" role="status">
          {t(message)}
        </p>
      )}
    </div>
  );
}
