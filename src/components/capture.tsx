'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
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
  RotateCcw,
  ShieldCheck,
  Trash2,
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
        aria-label={`Supprimer la prise ${frame.name}`}
        onClick={onDelete}
      >
        <Trash2 size={14} />
      </button>
      <span>{frame.name}</span>
    </div>
  );
}

export function Capture() {
  const search = useSearchParams();
  const dishId = search.get('dish') || '';
  const [sessionId, setSessionId] = useState('');
  const [frames, setFrames] = useState<CaptureFrame[]>([]);
  const [step, setStep] = useState(0);
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
  const camera = useRef<HTMLVideoElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const mounted = useRef(true);
  const cameraOpening = useRef(false);
  const bytes = frames.reduce((sum, frame) => sum + frame.size, 0);
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
        'Le stockage local est bloqué. Ouvrez cette page dans Safari ou Chrome, hors navigation privée.',
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
        if (alive) setError(`Impossible de vérifier la série distante. ${err.message}`);
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
      setError(err instanceof Error ? err.message : 'Cette série n’a pas pu être ouverte.');
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
        'Nouvelle série créée. Les prises précédentes restent accessibles dans la liste des séries.',
      );
    } catch {
      setError(
        'Impossible de créer une série. Vérifiez les permissions de stockage de votre navigateur.',
      );
    }
  }
  function stopCamera() {
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
        'La caméra demande une connexion HTTPS et un navigateur compatible. Ouvrez ce lien dans Safari ou Chrome. Vous pouvez aussi importer vos photos.',
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
      setStatus('Caméra ouverte. Les photos sont prises uniquement avec le bouton de capture.');
    } catch (err) {
      stopCamera();
      const code = err instanceof DOMException ? err.name : '';
      setError(
        code === 'NotAllowedError'
          ? 'L’accès à la caméra a été refusé. Autorisez-le dans les réglages du navigateur puis réessayez, ou importez vos photos.'
          : code === 'NotFoundError'
            ? 'Aucune caméra disponible. Importez des photos depuis votre appareil.'
            : 'La caméra n’a pas pu démarrer. Fermez les autres applications caméra puis réessayez, ou utilisez l’import.',
      );
    } finally {
      cameraOpening.current = false;
      if (mounted.current) setOpening(false);
    }
  }
  async function addFiles(files: FileList | File[]) {
    if (!sessionId || finalized) return;
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
            'Seules les photos JPEG, PNG et WebP sont importées. Convertissez les HEIC ou vidéos avant import. Les photos précédentes sont conservées.',
          );
        if (file.size > 25 * 1024 * 1024)
          throw new Error(
            'Cette photo dépasse 25 Mo. Exportez une copie plus légère avant import.',
          );
        validateImageBytes(new Uint8Array(await file.arrayBuffer()), file.type, 25 * 1024 * 1024);
        if (count >= 150 || total + file.size > CAPTURE_LIMIT)
          throw new Error(
            'Limite de cette série atteinte : 150 photos ou 100 Mo. Exportez vos originaux avant de préparer une autre série.',
          );
        await storeFrame(sessionId, file, file.name);
        count++;
        total += file.size;
        added++;
        setStatus(
          `${added} photo${added > 1 ? 's' : ''} enregistrée${added > 1 ? 's' : ''} sur cet appareil…`,
        );
      }
      if (navigator.storage?.persist) void navigator.storage.persist().catch(() => {});
      setStatus(
        `${added} photo${added > 1 ? 's' : ''} ajoutée${added > 1 ? 's' : ''}. Les originaux sont conservés dans ce navigateur.`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'L’import a échoué.');
    } finally {
      setFrames(await listFrames(sessionId).catch(() => frames));
      setBusy(false);
    }
  }
  async function takePhoto() {
    if (!camera.current?.videoWidth || busy) return;
    const video = camera.current;
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext('2d')!.drawImage(video, 0, 0);
    setBusy(true);
    canvas.toBlob(
      (blob) => {
        canvas.width = 0;
        canvas.height = 0;
        if (!blob) {
          setError('La prise n’a pas pu être enregistrée. Réessayez.');
          setBusy(false);
          return;
        }
        void addFiles([new File([blob], `prise-${Date.now()}.jpg`, { type: 'image/jpeg' })]);
      },
      'image/jpeg',
      0.95,
    );
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
            setStatus(`Export de l’original ${index + 1} / ${frames.length}…`);
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
                  note: 'Photos originales. Aucun modèle reconstruit ni couverture géométrique mesurée.',
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
        'Archive préparée. Vérifiez son enregistrement dans vos téléchargements. Les prises locales sont conservées.',
      );
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'L’export n’a pas pu être préparé. Vos prises sont conservées.',
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
            ? 'Cette série distante est annulée. Vos originaux sont conservés ; créez une nouvelle série pour poursuivre.'
            : 'Cette série est déjà finalisée. Vos originaux restent disponibles à l’export.',
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
          `Transfert vérifié : ${index + 1} / ${frames.length} photos. Une reprise ignore les images déjà reçues.`,
        );
      }
      setSynchronized(true);
      setStatus(
        'Photos transférées et vérifiées. Vous pouvez finaliser cette série ou ajouter des vues. Les originaux restent sur cet appareil.',
      );
    } catch (err) {
      setError(
        `${err instanceof Error ? err.message : 'Le transfert a été interrompu.'} Vos originaux sont conservés. Réessayez pour reprendre.`,
      );
    } finally {
      setBusy(false);
    }
  }
  async function finalize() {
    setBusy(true);
    setError('');
    try {
      await api(`/api/scans/${remoteId}/finalize`, { method: 'POST', body: '{}' });
      setFinalized(true);
      setRemoteState('finalized');
      setStatus(
        'Série finalisée : les fichiers reçus sont figés. Le calcul 3D nécessite un worker de reconstruction configuré.',
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Finalisation impossible.');
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="capture-page">
      <header className="capture-header container">
        <Brand />
        <Link href="/dashboard" className="subtle-link">
          <ArrowLeft size={16} /> Mon espace restaurant
        </Link>
      </header>
      <main id="main" className="container capture-main">
        <div className="capture-heading">
          <div>
            <p className="eyebrow">L’ATELIER DE CAPTURE</p>
            <h1>Gardez le bon angle.</h1>
            <p>Une série de photos, pour préparer la suite.</p>
          </div>
          <span className="capture-mode">
            <Camera size={16} /> Photos guidées · Navigateur
          </span>
        </div>
        <div className="capture-session-bar">
          <label htmlFor="capture-series">
            Série de photos
            <select
              id="capture-series"
              value={sessionId}
              disabled={busy || opening}
              onChange={(event) => void selectSession(event.target.value)}
            >
              {history.map((item, index) => (
                <option value={item.id} key={item.id}>
                  Série {index + 1} · {new Date(item.createdAt).toLocaleString('fr-FR')}
                </option>
              ))}
            </select>
          </label>
          <button
            className="button button-secondary button-small"
            disabled={busy || opening}
            onClick={() => void newSession()}
          >
            Nouvelle série
          </button>
        </div>
        <div className="capture-grid">
          <div>
            <div className="camera-stage">
              <video
                ref={camera}
                playsInline
                muted
                autoPlay
                aria-label="Aperçu de la caméra"
                className={live ? 'is-live' : ''}
              />
              {!live && (
                <div className="camera-placeholder">
                  <div>
                    <Focus size={50} strokeWidth={1} />
                  </div>
                  <h2>Tout commence par votre plat.</h2>
                  <p>
                    Ouvrez la caméra ou importez une série de photos. Placez l’assiette au centre du
                    cadre.
                  </p>
                  <button
                    className="button button-white"
                    onClick={openCamera}
                    disabled={busy || opening || !sessionId}
                  >
                    <Camera size={18} /> {opening ? 'Ouverture…' : 'Ouvrir la caméra'}
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
                    <span className="tiny-dot" /> CAMÉRA ACTIVE
                  </span>
                  <div className="camera-controls">
                    <button
                      className="icon-button"
                      onClick={stopCamera}
                      aria-label="Mettre la caméra en pause"
                    >
                      <Pause size={20} />
                    </button>
                    <button
                      className="shutter"
                      onClick={takePhoto}
                      disabled={busy || finalized}
                      aria-label="Prendre une photo"
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
            <div className="capture-import">
              <div>
                <ShieldCheck size={19} />
                <span>Originaux conservés sur cet appareil</span>
              </div>
              <input
                className="visually-hidden"
                ref={input}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                multiple
                aria-label="Importer les photos"
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
                <ImagePlus size={17} /> Importer des photos
              </button>
            </div>
            {error && (
              <div className="notice notice-error" role="alert">
                <Info size={18} />
                <p>{error}</p>
              </div>
            )}
            {status && (
              <p className="notice notice-success" role="status">
                {busy ? <LoaderCircle size={17} className="spin" /> : <Check size={17} />} {status}
              </p>
            )}
            <div className="capture-gallery-heading">
              <h2>
                Vos prises <span>{frames.length}</span>
              </h2>
              <span>{(bytes / 1024 / 1024).toFixed(1)} / 100 Mo</span>
            </div>
            {frames.length ? (
              <>
                <div className="capture-gallery">
                  {frames.slice(-4).map((frame) => (
                    <FrameThumbnail
                      key={frame.id}
                      frame={frame}
                      disabled={busy || finalized || Boolean(remoteId)}
                      onDelete={() => setDeleteId(frame.id)}
                    />
                  ))}
                </div>
                {frames.length > 4 && (
                  <p className="field-hint">
                    Les 4 dernières prises sont affichées. Les {frames.length} originaux sont inclus
                    dans l’export.
                  </p>
                )}
              </>
            ) : (
              <div className="capture-empty">
                <ImagePlus size={23} />
                <p>Vos premières prises apparaîtront ici.</p>
              </div>
            )}
            {deleteId && (
              <div className="notice notice-error">
                <p>Supprimer cet original de cet appareil ? Cette action est définitive.</p>
                <div className="button-row">
                  <button
                    className="button button-danger button-small"
                    disabled={busy}
                    onClick={async () => {
                      try {
                        await removeFrame(deleteId);
                        setFrames(await listFrames(sessionId));
                        setSynchronized(false);
                        setDeleteId('');
                      } catch {
                        setError('Impossible de supprimer cette prise.');
                      }
                    }}
                  >
                    Supprimer l’original
                  </button>
                  <button className="text-button" onClick={() => setDeleteId('')}>
                    Conserver
                  </button>
                </div>
              </div>
            )}
          </div>
          <aside className="capture-guide">
            <div className="guide-progress" aria-label="Étapes du guide">
              {guides.map((guide, index) => (
                <button
                  key={guide.title}
                  onClick={() => setStep(index)}
                  aria-label={`Conseil ${index + 1} : ${guide.title}`}
                  aria-current={step === index ? 'step' : undefined}
                >
                  {String(index + 1).padStart(2, '0')}
                </button>
              ))}
            </div>
            <p className="eyebrow">CONSEIL {step + 1} / 3</p>
            <h2>{guides[step].title}</h2>
            <p>{guides[step].text}</p>
            <div className="guide-tip">
              <Info size={18} />
              <p>{guides[step].detail}</p>
            </div>
            <button className="inline-link" onClick={() => setStep((step + 1) % 3)}>
              {step === 2 ? 'Revoir les conseils' : 'Conseil suivant'}
              {step === 2 ? <RotateCcw size={16} /> : <ArrowRight size={16} />}
            </button>
            <div className="capture-separator" />
            <h3>Votre série, bien gardée.</h3>
            <p className="field-hint">
              150 photos maximum, 100 Mo par série. Exportez vos originaux : le navigateur peut
              libérer son stockage. Le transfert prépare une copie allégée si nécessaire.
            </p>
            <button
              className="button button-dark"
              onClick={exportOriginals}
              disabled={busy || !frames.length}
            >
              <Download size={17} /> Exporter les originaux
            </button>
            {dishId ? (
              <>
                <button
                  className="button button-secondary"
                  onClick={uploadFrames}
                  disabled={busy || !frames.length || finalized}
                >
                  <CloudUpload size={17} />{' '}
                  {remoteId ? 'Reprendre le transfert' : 'Transférer vers le plat'}
                </button>
                {remoteId && !finalized && (
                  <button
                    className="button button-blue"
                    disabled={busy || frames.length < 3 || !synchronized}
                    onClick={finalize}
                  >
                    Finaliser la série <Check size={17} />
                  </button>
                )}
                {finalized && (
                  <p className="notice notice-success">
                    <Check size={17} />{' '}
                    {remoteState === 'cancelled'
                      ? 'Série annulée · Originaux conservés'
                      : 'Série finalisée'}
                  </p>
                )}
              </>
            ) : (
              <p className="field-hint">
                Pour associer ces photos à un plat, ouvrez la capture depuis sa fiche dans votre
                espace restaurant.
              </p>
            )}
            <div className="capture-truth">
              <Focus size={19} />
              <p>
                <strong>La photo d’abord.</strong> Ce parcours ne mesure ni poses ni couverture 3D.
                La reconstruction s’effectue ensuite avec un moteur séparé ; aucun calcul n’est
                lancé sur votre téléphone.
              </p>
            </div>
          </aside>
        </div>
      </main>
    </div>
  );
}
