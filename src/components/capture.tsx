'use client';
import { useI18n, LanguageSwitcher } from '@/components/language';

import { useEffect, useRef, useState } from 'react';
import { LocalizedLink as Link } from '@/components/language';
import { useSearchParams } from 'next/navigation';
import {
  ArrowLeft,
  ArrowRight,
  Camera,
  Check,
  CloudUpload,
  Download,
  Focus,
  ImagePlus,
  Info,
  LoaderCircle,
  Pause,
  ShieldCheck,
  Trash2,
  Sun,
  ScanLine,
  Hand,
  CircleAlert,
} from 'lucide-react';
import { Brand } from './brand';
import { api } from './api-client';
import {
  getOriginal,
  listFrames,
  removeFrame,
  sha256,
  storeFrame,
  uploadCopy,
  type CaptureFrame,
} from './capture-store';
import { validateImageBytes } from '@/lib/image-validation';
import { ReconstructionPanel } from './reconstruction-panel';
import { CaptureCoach } from './capture-coach';
import { useCaptureFeedback } from './capture-feedback';
import {
  capturePasses,
  inspectPixels,
  qualityMessages,
  type ImageQuality,
} from '@/lib/capture-quality';

const CAPTURE_LIMIT = 100 * 1024 * 1024;
const guides = [
  {
    title: 'Préparez la scène.',
    text: 'Une lumière diffuse, une table stable, votre plat immobile. Gardez assez de place pour en faire le tour.',
    detail: 'L’assiette ou le bol peut rester dans le cadre.',
  },
  {
    title: 'Faites le tour.',
    text: 'Photographiez à petits intervalles, avec beaucoup de recouvrement entre les vues. Déplacez le téléphone, pas le plat.',
    detail: 'Gardez la même lentille et évitez le zoom numérique.',
  },
  {
    title: 'Prenez de la hauteur.',
    text: 'Ajoutez un passage oblique puis des vues du dessus, surtout pour l’intérieur d’un bol. Ne retournez pas la nourriture.',
    detail: 'Le nombre de photos ne mesure pas la couverture 3D.',
  },
];

function FrameThumbnail({
  frame,
  onDelete,
  disabled,
}: {
  frame: CaptureFrame;
  onDelete: () => void;
  disabled: boolean;
}) {
  const { t } = useI18n();
  const [url, setUrl] = useState('');
  useEffect(() => {
    let alive = true;
    let objectUrl = '';
    getOriginal(frame.id)
      .then(async (blob) => {
        validateImageBytes(new Uint8Array(await blob.arrayBuffer()), blob.type, 25 * 1024 * 1024);
        const bitmap = await createImageBitmap(blob, { resizeWidth: 240 });
        const canvas = document.createElement('canvas');
        canvas.width = bitmap.width;
        canvas.height = bitmap.height;
        canvas.getContext('2d')!.drawImage(bitmap, 0, 0);
        bitmap.close();
        canvas.toBlob(
          (thumbnail) => {
            canvas.width = 0;
            canvas.height = 0;
            if (thumbnail && alive) {
              objectUrl = URL.createObjectURL(thumbnail);
              setUrl(objectUrl);
            }
          },
          'image/jpeg',
          0.6,
        );
      })
      .catch(() => {});
    return () => {
      alive = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [frame.id]);
  return (
    <div className="capture-thumbnail">
      {url ? <img src={url} alt={frame.name} /> : <ImagePlus size={24} />}
      <button
        className="icon-button"
        disabled={disabled}
        aria-label={t('Supprimer la prise {0}', [frame.name])}
        onClick={onDelete}
      >
        <Trash2 size={14} />
      </button>
      <span>{frame.name}</span>
      {frame.capture?.quality?.warnings.length ? (
        <small className="thumbnail-warning">
          <CircleAlert size={13} />
          {t('À contrôler')}
        </small>
      ) : null}
    </div>
  );
}

export function Capture() {
  const { t, numberLocale } = useI18n();
  const search = useSearchParams();
  const dishId = search.get('dish') || '';
  const [sessionId, setSessionId] = useState('');
  const [frames, setFrames] = useState<CaptureFrame[]>([]);
  const [live, setLive] = useState(false);
  const [opening, setOpening] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [remoteId, setRemoteId] = useState('');
  const [finalized, setFinalized] = useState(false);
  const [remoteState, setRemoteState] = useState('capturing');
  const [synchronized, setSynchronized] = useState(false);
  const [history, setHistory] = useState<{ id: string; createdAt: string }[]>([]);
  const [deleteId, setDeleteId] = useState('');
  const [pass, setPass] = useState(0);
  const [completed, setCompleted] = useState([false, false, false]);
  const [assisted, setAssisted] = useState(false);
  const [galleryPage, setGalleryPage] = useState(0);
  const operation = useRef(false);
  const lastShot = useRef(0);
  const camera = useRef<HTMLVideoElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const mounted = useRef(true);
  const cameraOpening = useRef(false);
  const { feedback, markCaptured } = useCaptureFeedback(camera, live);
  const takePhotoLatest = useRef<() => Promise<void>>(async () => {});
  useEffect(() => {
    takePhotoLatest.current = takePhoto;
  });
  useEffect(() => {
    if (
      assisted &&
      live &&
      !busy &&
      !finalized &&
      feedback?.ready &&
      Date.now() - lastShot.current > 2200
    )
      void takePhotoLatest.current();
  }, [assisted, live, busy, finalized, feedback]);
  useEffect(() => {
    setPass(0);
    setCompleted([false, false, false]);
    setGalleryPage(0);
    if (!sessionId) return;
    try {
      const plan = JSON.parse(localStorage.getItem(`dishplay-guide:${sessionId}`) || 'null');
      if (
        plan &&
        Number.isInteger(plan.pass) &&
        plan.pass >= 0 &&
        plan.pass < 3 &&
        Array.isArray(plan.completed) &&
        plan.completed.length === 3
      ) {
        setPass(plan.pass);
        setCompleted(plan.completed.map((v: unknown) => v === true));
      }
    } catch {
      /* Guidance is optional; originals are stored separately. */
    }
  }, [sessionId]);
  function updatePlan(nextPass: number, nextCompleted: boolean[]) {
    setPass(nextPass);
    setCompleted(nextCompleted);
    setAssisted(false);
    try {
      localStorage.setItem(
        `dishplay-guide:${sessionId}`,
        JSON.stringify({ pass: nextPass, completed: nextCompleted }),
      );
    } catch {
      /* Keep this session usable. */
    }
  }
  const bytes = frames.reduce((sum, frame) => sum + frame.size, 0);
  const passPhotos = frames.filter(
    (frame) => frame.capture?.source === 'camera' && frame.capture.pass === pass,
  ).length;
  useEffect(() => {
    mounted.current = true;
    try {
      const key = `dishplay-capture:${dishId || 'unlinked'}`;
      const id = localStorage.getItem(key) || crypto.randomUUID();
      localStorage.setItem(key, id);
      setSessionId(id);
      const rawHistory: unknown = JSON.parse(localStorage.getItem(`${key}:history`) || '[]');
      const savedHistory = Array.isArray(rawHistory)
        ? rawHistory.filter(
            (entry): entry is { id: string; createdAt: string } =>
              entry && typeof entry.id === 'string' && typeof entry.createdAt === 'string',
          )
        : [];
      if (!savedHistory.some((entry) => entry.id === id))
        savedHistory.push({ id, createdAt: new Date().toISOString() });
      localStorage.setItem(`${key}:history`, JSON.stringify(savedHistory));
      setHistory(savedHistory);
      const storedRemote = localStorage.getItem(`dishplay-remote:${id}`);
      if (storedRemote) setRemoteId(storedRemote);
      listFrames(id)
        .then(setFrames)
        .catch((err) => setError(err.message));
    } catch {
      setError(
        t(
          'Le stockage local est bloqué. Ouvrez cette page dans Safari ou Chrome, hors navigation privée.',
        ),
      );
    }
    return () => {
      mounted.current = false;
      stream.current?.getTracks().forEach((track) => track.stop());
    };
  }, [dishId]);
  useEffect(() => {
    if (!remoteId) return;
    let alive = true;
    api<{ scan: { state: string } }>(`/api/scans/${remoteId}`)
      .then((result) => {
        if (alive) {
          setRemoteState(result.scan.state);
          setFinalized(result.scan.state !== 'capturing');
        }
      })
      .catch((err) => {
        if (alive) setError(t('Impossible de vérifier la série distante. {0}', [err.message]));
      });
    return () => {
      alive = false;
    };
  }, [remoteId]);
  async function selectSession(id: string) {
    stopCamera();
    setBusy(true);
    setError('');
    setStatus('');
    try {
      setFrames(await listFrames(id));
      localStorage.setItem(`dishplay-capture:${dishId || 'unlinked'}`, id);
      setSessionId(id);
      setRemoteId(localStorage.getItem(`dishplay-remote:${id}`) || '');
      setRemoteState('capturing');
      setFinalized(false);
      setSynchronized(false);
      setDeleteId('');
    } catch (err) {
      setError(err instanceof Error ? err.message : t('Cette série n’a pas pu être ouverte.'));
    } finally {
      setBusy(false);
    }
  }
  async function newSession() {
    const id = crypto.randomUUID();
    const updated = [...history, { id, createdAt: new Date().toISOString() }];
    try {
      localStorage.setItem(
        `dishplay-capture:${dishId || 'unlinked'}:history`,
        JSON.stringify(updated),
      );
      setHistory(updated);
      await selectSession(id);
      setStatus(
        t(
          'Nouvelle série créée. Les prises précédentes restent accessibles dans la liste des séries.',
        ),
      );
    } catch {
      setError(
        t(
          'Impossible de créer une série. Vérifiez les permissions de stockage de votre navigateur.',
        ),
      );
    }
  }
  function stopCamera() {
    setAssisted(false);
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
    if (camera.current) camera.current.srcObject = null;
    setLive(false);
  }
  useEffect(() => {
    const pauseHidden = () => {
      if (document.hidden) stopCamera();
    };
    document.addEventListener('visibilitychange', pauseHidden);
    return () => document.removeEventListener('visibilitychange', pauseHidden);
  }, []);
  async function openCamera() {
    if (cameraOpening.current) return;
    setError('');
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      setError(
        t(
          'La caméra demande une connexion HTTPS et un navigateur compatible. Ouvrez ce lien dans Safari ou Chrome. Vous pouvez aussi importer vos photos.',
        ),
      );
      return;
    }
    cameraOpening.current = true;
    setOpening(true);
    stopCamera();
    try {
      const media = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: { ideal: 'environment' },
          width: { ideal: 1920 },
          height: { ideal: 1440 },
        },
      });
      if (!mounted.current || document.hidden) {
        media.getTracks().forEach((track) => track.stop());
        return;
      }
      stream.current = media;
      if (camera.current) {
        camera.current.srcObject = media;
        await camera.current.play();
      }
      if (!mounted.current || document.hidden || stream.current !== media) {
        media.getTracks().forEach((track) => track.stop());
        return;
      }
      setLive(true);
      setStatus(t('Caméra ouverte. Déclenchez une photo ou activez la prise assistée.'));
    } catch (err) {
      stopCamera();
      const code = err instanceof DOMException ? err.name : '';
      setError(
        code === 'NotAllowedError'
          ? t(
              'L’accès à la caméra a été refusé. Autorisez-le dans les réglages du navigateur puis réessayez, ou importez vos photos.',
            )
          : code === 'NotFoundError'
            ? t('Aucune caméra disponible. Importez des photos depuis votre appareil.')
            : t(
                'La caméra n’a pas pu démarrer. Fermez les autres applications caméra puis réessayez, ou utilisez l’import.',
              ),
      );
    } finally {
      cameraOpening.current = false;
      if (mounted.current) setOpening(false);
    }
  }
  async function addFiles(
    files: FileList | File[],
    captured?: { pass: number; quality?: ImageQuality; gray?: Uint8Array },
  ) {
    if (!sessionId || finalized) return;
    if (operation.current && !captured) return;
    operation.current = true;
    setBusy(true);
    setError('');
    setSynchronized(false);
    let count = frames.length;
    let total = bytes;
    let added = 0;
    try {
      for (const file of Array.from(files)) {
        if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type))
          throw new Error(
            t(
              'Seules les photos JPEG, PNG et WebP sont importées. Convertissez les HEIC ou vidéos avant import. Les photos précédentes sont conservées.',
            ),
          );
        if (file.size > 25 * 1024 * 1024)
          throw new Error(
            t('Cette photo dépasse 25 Mo. Exportez une copie plus légère avant import.'),
          );
        validateImageBytes(new Uint8Array(await file.arrayBuffer()), file.type, 25 * 1024 * 1024);
        if (count >= 150 || total + file.size > CAPTURE_LIMIT)
          throw new Error(
            t(
              'Limite de cette série atteinte : 150 photos ou 100 Mo. Exportez vos originaux avant de préparer une autre série.',
            ),
          );
        let quality = captured?.quality;
        if (!captured) {
          // Decode one small thumbnail at a time. Failure of advisory analysis
          // must never discard a valid original.
          try {
            const bitmap = await createImageBitmap(file, { resizeWidth: 160, resizeHeight: 120 });
            const canvas = document.createElement('canvas');
            canvas.width = 160;
            canvas.height = 120;
            const ctx = canvas.getContext('2d');
            if (ctx) {
              ctx.drawImage(bitmap, 0, 0);
              quality = inspectPixels(ctx.getImageData(0, 0, 160, 120).data, 160, 120).quality;
            }
            bitmap.close();
            canvas.width = 0;
            canvas.height = 0;
          } catch {
            /* Original import remains available. */
          }
        }
        await storeFrame(sessionId, file, file.name, {
          source: captured ? 'camera' : 'import',
          ...(captured ? { pass: captured.pass } : {}),
          ...(quality ? { quality } : {}),
        });
        count++;
        total += file.size;
        added++;
        setStatus(
          t('{0} photo{1} enregistrée{2} sur cet appareil…', [
            added,
            added > 1 ? 's' : '',
            added > 1 ? 's' : '',
          ]),
        );
      }
      if (navigator.storage?.persist) void navigator.storage.persist().catch(() => {});
      if (captured) markCaptured(captured.gray);
      setGalleryPage(0);
      setStatus(
        t('{0} photo{1} ajoutée{2}. Les originaux sont conservés dans ce navigateur.', [
          added,
          added > 1 ? 's' : '',
          added > 1 ? 's' : '',
        ]),
      );
    } catch (err) {
      setAssisted(false);
      setError(err instanceof Error ? err.message : t('L’import a échoué.'));
    } finally {
      setFrames(await listFrames(sessionId).catch(() => frames));
      setBusy(false);
      operation.current = false;
    }
  }
  async function takePhoto() {
    if (!camera.current?.videoWidth || busy || operation.current || finalized) return;
    operation.current = true;
    lastShot.current = Date.now();
    setBusy(true);
    const canvas = document.createElement('canvas');
    const sample = document.createElement('canvas');
    try {
      const video = camera.current;
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      const context = canvas.getContext('2d');
      if (!context) throw new Error(t('La prise n’a pas pu être enregistrée. Réessayez.'));
      context.drawImage(video, 0, 0);
      sample.width = 160;
      sample.height = 120;
      const small = sample.getContext('2d');
      small?.drawImage(canvas, 0, 0, 160, 120);
      const analysis = small
        ? inspectPixels(small.getImageData(0, 0, 160, 120).data, 160, 120)
        : null;
      const blob = await new Promise<Blob | null>((resolve) =>
        canvas.toBlob(resolve, 'image/jpeg', 0.95),
      );
      if (!blob) throw new Error(t('La prise n’a pas pu être enregistrée. Réessayez.'));
      await addFiles([new File([blob], `prise-${Date.now()}.jpg`, { type: 'image/jpeg' })], {
        pass,
        quality: analysis?.quality,
        gray: analysis?.gray,
      });
    } catch (err) {
      setError(
        err instanceof Error ? err.message : t('La prise n’a pas pu être enregistrée. Réessayez.'),
      );
      setAssisted(false);
    } finally {
      canvas.width = 0;
      canvas.height = 0;
      sample.width = 0;
      sample.height = 0;
      operation.current = false;
      setBusy(false);
    }
  }
  async function exportOriginals() {
    setBusy(true);
    setError('');
    stopCamera();
    try {
      const { Zip, ZipPassThrough, strToU8 } = await import('fflate');
      const chunks: BlobPart[] = [];
      const completion = new Promise<Blob>((resolve, reject) => {
        const zip = new Zip((err, chunk, final) => {
          if (err) reject(err);
          else {
            chunks.push(new Uint8Array(chunk));
            if (final) resolve(new Blob(chunks, { type: 'application/zip' }));
          }
        });
        void (async () => {
          for (const [index, frame] of frames.entries()) {
            setStatus(t('Export de l’original {0} / {1}…', [index + 1, frames.length]));
            const entry = new ZipPassThrough(
              `images/${String(index + 1).padStart(3, '0')}-${frame.name.replace(/[^a-zA-Z0-9._-]/g, '_')}`,
            );
            zip.add(entry);
            entry.push(new Uint8Array(await (await getOriginal(frame.id)).arrayBuffer()), true);
          }
          const manifest = new ZipPassThrough('manifest.json');
          zip.add(manifest);
          manifest.push(
            strToU8(
              JSON.stringify(
                {
                  schema: 'dishplay.capture.v1',
                  sessionId,
                  dishId: dishId || null,
                  source: 'browser-photos',
                  createdAt: new Date().toISOString(),
                  frames,
                  poses: null,
                  intrinsics: null,
                  note: t(
                    'Photos originales. Aucun modèle reconstruit ni couverture géométrique mesurée.',
                  ),
                },
                null,
                2,
              ),
            ),
            true,
          );
          zip.end();
        })().catch(reject);
      });
      const url = URL.createObjectURL(await completion);
      const link = document.createElement('a');
      link.href = url;
      link.download = `dishplay-capture-${sessionId.slice(0, 8)}.zip`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
      setStatus(
        t(
          'Archive préparée. Vérifiez son enregistrement dans vos téléchargements. Les prises locales sont conservées.',
        ),
      );
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : t('L’export n’a pas pu être préparé. Vos prises sont conservées.'),
      );
    } finally {
      setBusy(false);
    }
  }
  async function uploadFrames() {
    if (!dishId) return;
    setBusy(true);
    setError('');
    stopCamera();
    try {
      let id = remoteId;
      if (!id) {
        const result = await api<{ scan: { id: string } }>('/api/scans', {
          method: 'POST',
          body: JSON.stringify({ dishId }),
        });
        id = result.scan.id;
        setRemoteId(id);
        localStorage.setItem(`dishplay-remote:${sessionId}`, id);
      }
      const existing = await api<{ scan: { state: string }; frames: { sha256: string }[] }>(
        `/api/scans/${id}`,
      );
      if (existing.scan.state !== 'capturing') {
        setFinalized(true);
        setRemoteState(existing.scan.state);
        setStatus(
          existing.scan.state === 'cancelled'
            ? t(
                'Cette série distante est annulée. Vos originaux sont conservés ; créez une nouvelle série pour poursuivre.',
              )
            : t('Cette série est déjà finalisée. Vos originaux restent disponibles à l’export.'),
        );
        return;
      }
      const known = new Set(existing.frames.map((frame) => frame.sha256));
      for (const [index, frame] of frames.entries()) {
        const copy = await uploadCopy(await getOriginal(frame.id));
        const hash = await sha256(copy);
        if (!known.has(hash)) {
          await api(`/api/scans/${id}/frames`, {
            method: 'POST',
            headers: { 'Content-Type': copy.type, 'X-Content-SHA256': hash },
            body: copy,
          });
          known.add(hash);
        }
        setStatus(
          t('Transfert vérifié : {0} / {1} photos. Une reprise ignore les images déjà reçues.', [
            index + 1,
            frames.length,
          ]),
        );
      }
      setSynchronized(true);
      setStatus(
        t(
          'Photos transférées et vérifiées. Vous pouvez finaliser cette série ou ajouter des vues. Les originaux restent sur cet appareil.',
        ),
      );
    } catch (err) {
      setError(
        t('{0} Vos originaux sont conservés. Réessayez pour reprendre.', [
          err instanceof Error ? err.message : t('Le transfert a été interrompu.'),
        ]),
      );
    } finally {
      setBusy(false);
    }
  }
  async function finalize() {
    stopCamera();
    setBusy(true);
    setError('');
    try {
      await api(`/api/scans/${remoteId}/finalize`, { method: 'POST', body: '{}' });
      setFinalized(true);
      setRemoteState('finalized');
      setStatus(
        t(
          'Série finalisée : les fichiers reçus sont figés. Le calcul 3D nécessite un worker de reconstruction configuré.',
        ),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : t('Finalisation impossible.'));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="capture-page">
      <header className="capture-header container">
        <Brand />
        <LanguageSwitcher />
        <Link href="/dashboard" className="subtle-link">
          <ArrowLeft size={16} /> {t('Mon espace restaurant')}{' '}
        </Link>
      </header>
      <main id="main" className="container capture-main">
        <div className="capture-heading">
          <div>
            <p className="eyebrow">{t('L’ATELIER DE CAPTURE')}</p>
            <h1>{t('Gardez le bon angle.')}</h1>
            <p>{t('Tournez autour du plat. On vous guide, une vue à la fois.')}</p>
          </div>
          <span className="capture-mode">
            <Camera size={16} /> {t('Photos guidées · Navigateur')}{' '}
          </span>
        </div>
        <div className="capture-session-bar">
          <label htmlFor="capture-series">
            {' '}
            {t('Série de photos')}{' '}
            <select
              id="capture-series"
              value={sessionId}
              disabled={busy || opening}
              onChange={(event) => void selectSession(event.target.value)}
            >
              {history.map((item, index) => (
                <option value={item.id} key={item.id}>
                  {' '}
                  {t('Série')} {index + 1} · {new Date(item.createdAt).toLocaleString(numberLocale)}
                </option>
              ))}
            </select>
          </label>
          <button
            className="button button-secondary button-small"
            disabled={busy || opening}
            onClick={() => void newSession()}
          >
            {' '}
            {t('Nouvelle série')}{' '}
          </button>
        </div>
        <CaptureCoach
          pass={pass}
          completed={completed}
          frames={frames}
          disabled={busy || opening || finalized}
          live={live}
          onChange={updatePlan}
        />
        <div className="capture-grid">
          <div>
            <div className="camera-stage">
              <video
                ref={camera}
                playsInline
                muted
                autoPlay
                aria-label={t('Aperçu de la caméra')}
                className={live ? 'is-live' : ''}
              />
              {!live && (
                <div className="camera-placeholder">
                  <div>
                    <Focus size={50} strokeWidth={1} />
                  </div>
                  <h2>{t('Tout commence par votre plat.')}</h2>
                  <p>
                    {' '}
                    {t(
                      'Ouvrez la caméra ou importez une série de photos. Placez l’assiette au centre du cadre.',
                    )}{' '}
                  </p>
                  <button
                    className="button button-white"
                    onClick={openCamera}
                    disabled={busy || opening || !sessionId}
                  >
                    <Camera size={18} /> {opening ? t('Ouverture…') : t('Ouvrir la caméra')}
                  </button>
                </div>
              )}
              {live && (
                <>
                  <div className="camera-corners" aria-hidden="true">
                    <i />
                    <i />
                    <i />
                    <i />
                  </div>
                  <span className="live-label">
                    <span className="tiny-dot" /> {t('CAMÉRA ACTIVE')}{' '}
                  </span>
                  <span className="live-pass">
                    {t('PASSAGE {0} / 3', [pass + 1])} · {capturePasses[pass].angle}
                  </span>
                  <p className="live-coaching" aria-live="polite">
                    {feedback?.quality.warnings.length
                      ? t(qualityMessages[feedback.quality.warnings[0]])
                      : feedback?.moving
                        ? t('Arrêtez-vous un instant.')
                        : feedback?.similar
                          ? t('Avancez d’un petit pas autour du plat.')
                          : feedback
                            ? t('Image stable. Vous pouvez prendre la photo.')
                            : t('Analyse de l’image…')}
                  </p>
                  <div className="camera-controls">
                    <button
                      className="icon-button"
                      onClick={stopCamera}
                      aria-label={t('Mettre la caméra en pause')}
                    >
                      <Pause size={20} />
                    </button>
                    <button
                      className="shutter"
                      onClick={takePhoto}
                      disabled={busy || finalized}
                      aria-label={t('Prendre une photo')}
                    >
                      <span />
                    </button>
                    <span>
                      {frames.length} photo{frames.length !== 1 ? 's' : ''}
                    </span>
                  </div>
                </>
              )}
            </div>
            {live && (
              <div className="camera-next-pass">
                <div>
                  <strong>{t(capturePasses[pass].short)}</strong>
                  <span>{t('Photos dans ce passage : {0}', [passPhotos])}</span>
                </div>
                <button
                  className="inline-link"
                  disabled={busy || finalized || !passPhotos}
                  onClick={() => {
                    const next = [...completed];
                    next[pass] = true;
                    updatePlan(Math.min(2, pass + 1), next);
                    if (pass === 2) stopCamera();
                  }}
                >
                  {t('J’ai fait tout le tour')}
                  <ArrowRight size={16} />
                </button>
              </div>
            )}
            <div className="photo-feedback" aria-label={t('Contrôle de l’image')}>
              <div>
                <Sun size={18} />
                <span>
                  {t('Lumière')}
                  <strong>
                    {!feedback
                      ? t('En attente de la caméra')
                      : feedback.quality.warnings.includes('dark')
                        ? t('Trop sombre')
                        : feedback.quality.warnings.includes('bright')
                          ? t('Trop forte')
                          : t('Correcte')}
                  </strong>
                </span>
              </div>
              <div>
                <Hand size={18} />
                <span>
                  {t('Stabilité')}
                  <strong>
                    {!feedback
                      ? t('En attente de la caméra')
                      : feedback.moving
                        ? t('Faites une pause')
                        : t('Image stable')}
                  </strong>
                </span>
              </div>
              <div>
                <ScanLine size={18} />
                <span>
                  {t('Détails')}
                  <strong>
                    {!feedback
                      ? t('En attente de la caméra')
                      : feedback.quality.warnings.includes('detail')
                        ? t('À contrôler')
                        : t('Détectés')}
                  </strong>
                </span>
              </div>
            </div>
            <div className="assisted-control">
              <label>
                <input
                  type="checkbox"
                  checked={assisted}
                  disabled={!live || finalized || busy}
                  onChange={(e) => setAssisted(e.target.checked)}
                />
                {t('Prise assistée')}
              </label>
              <p>
                {t(
                  'Une photo après une courte pause, si l’image a changé et si les contrôles passent. Gardez le plat centré. Vous pouvez toujours déclencher vous-même.',
                )}
              </p>
            </div>
            <p className="feedback-note">
              {t(
                'Indications estimées sur l’image : elles ne vérifient ni le cadrage, ni les angles couverts, ni la réussite du futur modèle 3D.',
              )}
            </p>
            <div className="capture-import">
              <div>
                <ShieldCheck size={19} />
                <span>{t('Originaux conservés sur cet appareil')}</span>
              </div>
              <input
                className="visually-hidden"
                ref={input}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                multiple
                disabled={busy || finalized || !sessionId}
                aria-label={t('Importer les photos')}
                onChange={(event) => {
                  if (event.target.files?.length) void addFiles(event.target.files);
                  event.target.value = '';
                }}
              />
              <button
                className="button button-secondary button-small"
                onClick={() => input.current?.click()}
                disabled={busy || !sessionId || finalized}
              >
                <ImagePlus size={17} /> {t('Importer des photos')}{' '}
              </button>
            </div>
            {error && (
              <div className="notice notice-error" role="alert">
                <Info size={18} />
                <p>{t(error)}</p>
              </div>
            )}
            {status && (
              <p className="notice notice-success" role="status">
                {busy ? <LoaderCircle size={17} className="spin" /> : <Check size={17} />}{' '}
                {t(status)}
              </p>
            )}
            <div className="capture-gallery-heading">
              <h2>
                {' '}
                {t('Vos prises')} <span>{frames.length}</span>
              </h2>
              <span>
                {(bytes / 1024 / 1024).toFixed(1)} {t('/ 100 Mo')}
              </span>
            </div>
            {frames.length ? (
              <>
                <div className="capture-gallery">
                  {[...frames]
                    .reverse()
                    .slice(galleryPage * 4, galleryPage * 4 + 4)
                    .map((frame) => (
                      <FrameThumbnail
                        key={frame.id}
                        frame={frame}
                        disabled={busy || finalized || Boolean(remoteId)}
                        onDelete={() => setDeleteId(frame.id)}
                      />
                    ))}
                </div>
                {frames.length > 4 && (
                  <div className="gallery-pagination">
                    <button
                      className="text-button"
                      disabled={galleryPage === 0}
                      onClick={() => setGalleryPage((p) => p - 1)}
                    >
                      {t('Précédent')}
                    </button>
                    <span>
                      {galleryPage + 1} / {Math.ceil(frames.length / 4)}
                    </span>
                    <button
                      className="text-button"
                      disabled={(galleryPage + 1) * 4 >= frames.length}
                      onClick={() => setGalleryPage((p) => p + 1)}
                    >
                      {t('Suivant')}
                    </button>
                  </div>
                )}
              </>
            ) : (
              <div className="capture-empty">
                <ImagePlus size={23} />
                <p>{t('Vos premières prises apparaîtront ici.')}</p>
              </div>
            )}
            {frames.some((f) => f.capture?.quality?.warnings.length) && (
              <div className="quality-review">
                <h3>{t('À revoir avant le transfert')}</h3>
                <p>
                  {t(
                    'Ces indices invitent à vérifier les photos. Les originaux sont conservés, même lorsqu’un contrôle signale un problème.',
                  )}
                </p>
                <ul>
                  {frames
                    .filter((f) => f.capture?.quality?.warnings.length)
                    .map((f) => (
                      <li key={f.id}>
                        <strong>{f.name}</strong>
                        <span>
                          {f.capture!.quality!.warnings.map((w) => t(qualityMessages[w])).join(' ')}
                        </span>
                      </li>
                    ))}
                </ul>
              </div>
            )}
            {deleteId && (
              <div className="notice notice-error">
                <p>{t('Supprimer cet original de cet appareil ? Cette action est définitive.')}</p>
                <div className="button-row">
                  <button
                    className="button button-danger button-small"
                    disabled={busy}
                    onClick={async () => {
                      try {
                        await removeFrame(deleteId);
                        setFrames(await listFrames(sessionId));
                        setGalleryPage(0);
                        setSynchronized(false);
                        setDeleteId('');
                      } catch {
                        setError(t('Impossible de supprimer cette prise.'));
                      }
                    }}
                  >
                    {' '}
                    {t('Supprimer l’original')}{' '}
                  </button>
                  <button className="text-button" onClick={() => setDeleteId('')}>
                    {' '}
                    {t('Conserver')}{' '}
                  </button>
                </div>
              </div>
            )}
          </div>
          <aside className="capture-guide">
            <details className="preparation-tips">
              <summary>{t('Avant de commencer')}</summary>
              {guides.map((guide) => (
                <div key={guide.title}>
                  <h3>{t(guide.title)}</h3>
                  <p>{t(guide.text)}</p>
                </div>
              ))}
            </details>
            <div className="capture-separator" />
            <h3>{t('Votre série, bien gardée.')}</h3>
            <p className="field-hint">
              {' '}
              {t(
                '150 photos maximum, 100 Mo par série. Exportez vos originaux : le navigateur peut libérer son stockage. Le transfert prépare une copie allégée si nécessaire.',
              )}{' '}
            </p>
            <button
              className="button button-dark"
              onClick={exportOriginals}
              disabled={busy || !frames.length}
            >
              <Download size={17} /> {t('Exporter les originaux')}{' '}
            </button>
            {dishId ? (
              <>
                <button
                  className="button button-secondary"
                  onClick={uploadFrames}
                  disabled={busy || !frames.length || finalized}
                >
                  <CloudUpload size={17} />{' '}
                  {remoteId ? t('Reprendre le transfert') : t('Transférer vers le plat')}
                </button>
                {remoteId && !finalized && (
                  <button
                    className="button button-blue"
                    disabled={busy || frames.length < 3 || !synchronized}
                    onClick={finalize}
                  >
                    {' '}
                    {t('Finaliser la série')} <Check size={17} />
                  </button>
                )}
                {finalized && (
                  <p className="notice notice-success">
                    <Check size={17} />{' '}
                    {remoteState === 'cancelled'
                      ? t('Série annulée · Originaux conservés')
                      : t('Série finalisée')}
                  </p>
                )}
                {remoteId && remoteState === 'finalized' && (
                  <ReconstructionPanel scanId={remoteId} />
                )}
              </>
            ) : (
              <p className="field-hint">
                {' '}
                {t(
                  'Pour associer ces photos à un plat, ouvrez la capture depuis sa fiche dans votre espace restaurant.',
                )}{' '}
              </p>
            )}
            <div className="capture-truth">
              <Focus size={19} />
              <p>
                <strong>{t('La photo d’abord.')}</strong>{' '}
                {t(
                  'Ce parcours ne mesure ni poses ni couverture 3D. La reconstruction s’effectue ensuite avec un moteur séparé ; aucun calcul n’est lancé sur votre téléphone.',
                )}{' '}
              </p>
            </div>
          </aside>
        </div>
      </main>
    </div>
  );
}
