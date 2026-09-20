'use client';
import { useEffect, useRef, useState } from 'react';
import { useI18n } from './language';
import type { ModelViewerElement } from '@google/model-viewer';

export function ReconstructionDownload({ id }: { id: string }) {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [preview, setPreview] = useState('');
  const previewURL = useRef('');
  const controller = useRef<AbortController | null>(null);
  useEffect(
    () => () => {
      controller.current?.abort();
      if (previewURL.current) URL.revokeObjectURL(previewURL.current);
    },
    [],
  );
  async function download(kind: 'glb' | 'usdz', explore = false) {
    setBusy(true);
    setError('');
    const abort = new AbortController();
    controller.current = abort;
    try {
      const chunks: Uint8Array<ArrayBuffer>[] = [];
      let count = 1,
        bytes = 0,
        expected = 0,
        hash = '';
      for (let part = 0; part < count; part++) {
        const response = await fetch(`/api/reconstruction/${id}/${kind}?part=${part}`, {
          signal: abort.signal,
        });
        if (!response.ok) throw new Error(t('Le téléchargement a échoué. Réessayez.'));
        const parts = Number(response.headers.get('X-Artifact-Parts'));
        const size = Number(response.headers.get('X-Artifact-Bytes'));
        const checksum = response.headers.get('X-Artifact-SHA256') || '';
        if (
          !Number.isInteger(parts) ||
          parts < 1 ||
          parts > 128 ||
          !Number.isInteger(size) ||
          size <= 0 ||
          size > 128 * 1024 * 1024 ||
          !/^[a-f0-9]{64}$/.test(checksum)
        )
          throw new Error(t('Modèle invalide.'));
        if (part === 0) {
          count = parts;
          expected = size;
          hash = checksum;
        }
        if (count !== parts || size !== expected || checksum !== hash)
          throw new Error(t('Modèle invalide.'));
        const chunk = new Uint8Array(await response.arrayBuffer());
        if (chunk.length > 1024 * 1024) throw new Error(t('Modèle invalide.'));
        chunks.push(chunk);
        bytes += chunk.length;
      }
      if (bytes !== expected) throw new Error(t('Modèle invalide.'));
      const file = new Blob(chunks, {
        type: kind === 'glb' ? 'model/gltf-binary' : 'model/vnd.usdz+zip',
      });
      const digest = [
        ...new Uint8Array(await crypto.subtle.digest('SHA-256', await file.arrayBuffer())),
      ]
        .map((v) => v.toString(16).padStart(2, '0'))
        .join('');
      if (digest !== hash) throw new Error(t('Modèle invalide.'));
      const url = URL.createObjectURL(file);
      if (explore) {
        if (previewURL.current) URL.revokeObjectURL(previewURL.current);
        previewURL.current = url;
        setPreview(url);
        return;
      }
      const link = document.createElement('a');
      link.href = url;
      link.download = `dishplay-${id}.${kind}`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (err) {
      if (!abort.signal.aborted)
        setError(err instanceof Error ? err.message : t('Le téléchargement a échoué. Réessayez.'));
    } finally {
      if (!abort.signal.aborted) setBusy(false);
    }
  }
  return (
    <div className="form-stack">
      <button
        className="button button-blue"
        disabled={busy}
        onClick={() => void download('glb', true)}
      >
        {t('Explorer le résultat en 3D')}
      </button>
      {preview && <PrivateModel src={preview} />}
      <button className="button button-blue" disabled={busy} onClick={() => void download('glb')}>
        {t('Télécharger le modèle GLB')}
      </button>
      <button
        className="button button-secondary"
        disabled={busy}
        onClick={() => void download('usdz')}
      >
        {t('Télécharger pour iPhone (USDZ)')}
      </button>
      {busy && <p role="status">{t('Réception et vérification du modèle…')}</p>}
      {error && <p role="alert">{error}</p>}
    </div>
  );
}

function PrivateModel({ src }: { src: string }) {
  const { t } = useI18n();
  const mount = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  useEffect(() => {
    const abort = new AbortController();
    let viewer: ModelViewerElement | undefined;
    setStatus('loading');
    const timeout = setTimeout(() => {
      setStatus('error');
      abort.abort();
      viewer?.remove();
    }, 30_000);
    void import('@google/model-viewer')
      .then(({ ModelViewerElement }) => {
        if (abort.signal.aborted || !mount.current) return;
        ModelViewerElement.modelCacheSize = 1;
        viewer = document.createElement('model-viewer') as ModelViewerElement;
        viewer.setAttribute('src', src);
        viewer.setAttribute('alt', t('Résultat de votre reconstruction, à vérifier'));
        viewer.setAttribute('camera-controls', '');
        viewer.setAttribute('touch-action', 'pan-y');
        viewer.style.cssText =
          'display:block;width:100%;height:340px;background:#f4f5f7;border-radius:16px';
        viewer.addEventListener(
          'load',
          () => {
            clearTimeout(timeout);
            setStatus('ready');
          },
          { signal: abort.signal },
        );
        viewer.addEventListener(
          'error',
          () => {
            clearTimeout(timeout);
            setStatus('error');
            viewer?.remove();
          },
          { signal: abort.signal },
        );
        mount.current.append(viewer);
      })
      .catch(() => {
        if (!abort.signal.aborted) {
          clearTimeout(timeout);
          setStatus('error');
        }
      });
    return () => {
      clearTimeout(timeout);
      abort.abort();
      viewer?.remove();
    };
  }, [src, t]);
  return (
    <div>
      <div ref={mount} />
      {status === 'loading' && <p role="status">{t('Chargement de la 3D…')}</p>}
      {status === 'error' && (
        <p role="alert">{t('L’aperçu n’a pas pu s’ouvrir. Le modèle reste téléchargeable.')}</p>
      )}
    </div>
  );
}
