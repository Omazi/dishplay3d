'use client';

import { useEffect, useState } from 'react';
import { Smartphone, Copy, ArrowUpRight } from 'lucide-react';
import { api } from './api-client';
import { LocalizedLink as Link, useI18n } from './language';
import { ReconstructionPanel } from './reconstruction-panel';
import type { RestaurantWorkspace } from '@/lib/contracts';

type CaptureLink = {
  id: string;
  scanId: string | null;
  claimedAt: string | null;
  revokedAt: string | null;
  codeExpiresAt: string;
  tokenExpiresAt: string | null;
  state: string | null;
  frameCount: number;
};
type Receipt = { scan: { state: string }; frames: { id: string; mediaId: string; url: string }[] };

export function NativeCapturePanel({ dishId }: { dishId: string }) {
  const { t, numberLocale } = useI18n();
  const [pair, setPair] = useState<{ id: string; code: string; expiresAt: string } | null>(null);
  const [links, setLinks] = useState<CaptureLink[]>([]);
  const [selected, setSelected] = useState('');
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [page, setPage] = useState(0);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    async function refresh() {
      try {
        if (!document.hidden) {
          const data = await api<{ links: CaptureLink[] }>(
            `/api/capture-links?dishId=${encodeURIComponent(dishId)}`,
            { signal: controller.signal },
          );
          if (alive) setLinks(data.links);
          if (selected) {
            const received = await api<Receipt>(`/api/scans/${selected}`, {
              signal: controller.signal,
            });
            if (alive) setReceipt(received);
          }
        }
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : 'Suivi indisponible.');
      } finally {
        if (alive) timer = setTimeout(refresh, 10_000);
      }
    }
    void refresh();
    return () => {
      alive = false;
      controller.abort();
      clearTimeout(timer);
    };
  }, [dishId, selected, revision]);
  async function action(work: () => Promise<void>) {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await work();
      setRevision((n) => n + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'La demande a échoué.');
    } finally {
      setBusy(false);
    }
  }
  const activePair = pair && links.find((link) => link.id === pair.id);
  const codeAvailable =
    pair &&
    new Date(pair.expiresAt).getTime() > Date.now() &&
    !activePair?.claimedAt &&
    !activePair?.revokedAt;
  return (
    <section className="native-capture-panel" aria-labelledby="native-capture-title">
      <div className="native-capture-intro">
        <div className="native-capture-icon">
          <Smartphone size={28} />
        </div>
        <div>
          <p className="eyebrow">{t('CAPTURE SPATIALE · IPHONE')}</p>
          <h2 id="native-capture-title">{t('Le volume. Les points. Votre plat.')}</h2>
          <p>
            {t(
              'Dans l’app iPhone, appuyez sur Scanner le plat et suivez l’orbite. La capture choisit les bonnes vues et montre les points réellement observés.',
            )}
          </p>
        </div>
      </div>
      <ol className="native-capture-steps">
        <li>
          <strong>{t('1. Capturez sur iPhone')}</strong>
          <span>
            {t(
              'Installez la dernière version de DishPlay Capture. Le scan guidé utilise ARKit, même sans Object Capture ; vous pouvez aussi importer des photos.',
            )}
          </span>
        </li>
        <li>
          <strong>{t('2. Associez ce plat')}</strong>
          <span>
            {t(
              'Créez un code privé valable 10 minutes et saisissez-le dans l’app. Vous pouvez associer le plat avant le scan.',
            )}
          </span>
        </li>
        <li>
          <strong>{t('3. Vérifiez puis envoyez')}</strong>
          <span>
            {t(
              'Continuez après le scan : l’app envoie les vues, votre PC reconstruit le plat et le modèle revient dans l’app. Les originaux restent sur l’iPhone.',
            )}
          </span>
        </li>
      </ol>
      <p className="field-hint">
        {t(
          'L’app iPhone est en phase de test et nécessite une installation signée. Elle n’est pas encore disponible sur l’App Store. Android viendra ensuite.',
        )}
      </p>
      <div className="button-row">
        <button
          type="button"
          className="button button-dark"
          disabled={busy}
          onClick={() =>
            void action(async () => {
              setPair(
                await api('/api/capture-links', {
                  method: 'POST',
                  body: JSON.stringify({ dishId }),
                }),
              );
            })
          }
        >
          {t('Créer un code pour l’iPhone')}
        </button>
      </div>
      {pair && codeAvailable && (
        <div className="native-pair-code">
          <div>
            <span>{t('Code privé à usage unique')}</span>
            <strong>{pair.code}</strong>
            <small>
              {t('Expire à {0}', [
                new Date(pair.expiresAt).toLocaleTimeString(numberLocale, {
                  hour: '2-digit',
                  minute: '2-digit',
                }),
              ])}
            </small>
          </div>
          <div className="button-row">
            <button
              type="button"
              className="button button-secondary button-small"
              onClick={() =>
                void action(async () => {
                  await navigator.clipboard.writeText(pair.code);
                  setNotice('Code copié.');
                })
              }
            >
              <Copy size={15} />
              {t('Copier le code')}
            </button>
            <a
              className="button button-secondary button-small"
              href={`dishplaycapture://pair?code=${encodeURIComponent(pair.code)}`}
            >
              <ArrowUpRight size={15} />
              {t('Ouvrir l’app installée')}
            </a>
          </div>
          <small>
            {t('Si l’app ne s’ouvre pas, copiez ce code dans « Associer au site » sur l’iPhone.')}
          </small>
        </div>
      )}
      {pair && !codeAvailable && (
        <p className="field-hint">
          {t('Ce code est utilisé, expiré ou révoqué. Créez-en un nouveau si nécessaire.')}
        </p>
      )}
      {links.length > 0 && (
        <div className="native-receipts">
          <h3>{t('Captures iPhone de ce plat')}</h3>
          {links.map((link) => {
            const expired =
              new Date(link.tokenExpiresAt || link.codeExpiresAt).getTime() <= Date.now();
            return (
              <div className="native-receipt" key={link.id}>
                <div>
                  <strong>
                    {t(
                      link.state === 'finalized'
                        ? 'Série finalisée'
                        : link.state === 'cancelled'
                          ? 'Série annulée'
                          : link.claimedAt
                            ? 'iPhone associé'
                            : 'En attente de l’iPhone',
                    )}
                  </strong>
                  <span>
                    {t('{0} photos reçues', [link.frameCount])} ·{' '}
                    {t(link.revokedAt ? 'Accès révoqué' : expired ? 'Accès expiré' : 'Accès actif')}
                  </span>
                </div>
                <div className="button-row">
                  {link.scanId && (
                    <button
                      type="button"
                      className="button button-secondary button-small"
                      onClick={() => {
                        setSelected(link.scanId!);
                        setPage(0);
                        setReceipt(null);
                      }}
                    >
                      {t('Voir les photos reçues')}
                    </button>
                  )}
                  {!link.revokedAt && !expired && (
                    <button
                      type="button"
                      className="text-button"
                      disabled={busy}
                      onClick={() =>
                        void action(async () => {
                          await api(`/api/capture-links/${link.id}`, { method: 'DELETE' });
                        })
                      }
                    >
                      {t('Révoquer l’accès')}
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
      {receipt && (
        <div className="native-received-gallery">
          <h3>{t('Photos reçues sur le site')}</h3>
          {receipt.frames.length === 0 && (
            <p>{t('Aucune photo reçue. Lancez l’envoi depuis l’iPhone.')}</p>
          )}
          <div className="native-photo-grid">
            {receipt.frames.slice(page * 4, page * 4 + 4).map((frame, index) => (
              <figure key={frame.id}>
                <img
                  src={frame.url}
                  alt={t('Photo reçue {0}', [page * 4 + index + 1])}
                  loading="lazy"
                />
                <button
                  type="button"
                  className="text-button"
                  disabled={busy}
                  onClick={() =>
                    void action(async () => {
                      const workspace = await api<RestaurantWorkspace>('/api/restaurant');
                      const dish = workspace.dishes.find((d) => d.id === dishId);
                      if (!dish) throw new Error('Dish not found.');
                      await api(`/api/dishes/${dishId}`, {
                        method: 'PATCH',
                        body: JSON.stringify({ version: dish.version, imageId: frame.mediaId }),
                      });
                      setNotice(
                        'Photo ajoutée au brouillon. Publiez la carte depuis votre espace restaurant.',
                      );
                    })
                  }
                >
                  {t('Choisir pour la fiche du plat')}
                </button>
              </figure>
            ))}
          </div>
          {receipt.frames.length > 4 && (
            <div className="button-row">
              <button
                type="button"
                className="text-button"
                disabled={page === 0}
                onClick={() => setPage((n) => n - 1)}
              >
                {t('Précédent')}
              </button>
              <span>
                {page + 1} / {Math.ceil(receipt.frames.length / 4)}
              </span>
              <button
                type="button"
                className="text-button"
                disabled={(page + 1) * 4 >= receipt.frames.length}
                onClick={() => setPage((n) => n + 1)}
              >
                {t('Suivant')}
              </button>
            </div>
          )}
          {receipt.scan.state === 'capturing' && (
            <div className="button-row">
              <button
                type="button"
                className="button button-secondary button-small"
                disabled={busy || receipt.frames.length < 3}
                onClick={() =>
                  void action(async () => {
                    await api(`/api/scans/${selected}/finalize`, { method: 'POST' });
                  })
                }
              >
                {t('Finaliser les photos reçues')}
              </button>
              <button
                type="button"
                className="text-button"
                disabled={busy}
                onClick={() =>
                  void action(async () => {
                    await api(`/api/scans/${selected}`, { method: 'DELETE' });
                  })
                }
              >
                {t('Annuler cette série')}
              </button>
              <p className="field-hint">
                {t(
                  'Finaliser ferme la série aux nouveaux envois. Attendez la fin du transfert sur l’iPhone.',
                )}
              </p>
            </div>
          )}
          {receipt.scan.state === 'finalized' && <ReconstructionPanel scanId={selected} />}
          <Link className="inline-link" href="/dashboard">
            {t('Mon espace restaurant')} <ArrowUpRight size={16} />
          </Link>
        </div>
      )}
      {notice && (
        <p className="notice" role="status">
          {t(notice)}
        </p>
      )}
      {error && (
        <p className="notice notice-error" role="alert">
          {t(error)}
        </p>
      )}
    </section>
  );
}
