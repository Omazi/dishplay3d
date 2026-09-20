'use client';
import { useI18n } from '@/components/language';

import { useEffect, useState } from 'react';
import { api } from './api-client';

type Job = {
  id: string;
  scanId: string;
  state: string;
  stage: string | null;
  errorCode: string | null;
};
type Queue = { jobs: Job[]; enabled: boolean; workerAvailable: boolean };
const labels: Record<string, string> = {
  queued: 'En attente',
  running: 'Calcul en cours',
  ready_for_review: 'À vérifier',
  failed: 'Calcul interrompu',
  cancelled: 'Calcul annulé',
  succeeded: 'Calcul terminé',
};

export function ReconstructionPanel({ scanId }: { scanId: string }) {
  const { t } = useI18n();
  const [queue, setQueue] = useState<Queue | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    const refresh = async () => {
      if (document.hidden) {
        if (alive) timer = setTimeout(refresh, 15_000);
        return;
      }
      let shouldRefresh = true;
      try {
        const result = await api<Queue>('/api/reconstruction', { signal: controller.signal });
        const scanJobs = result.jobs.filter((job) => job.scanId === scanId);
        shouldRefresh =
          result.enabled &&
          (scanJobs.length === 0 ||
            scanJobs.some((job) => ['queued', 'running'].includes(job.state)));
        if (alive) {
          setQueue(result);
          setError('');
        }
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : t('Suivi indisponible.'));
      } finally {
        if (alive && shouldRefresh) timer = setTimeout(refresh, 10_000);
      }
    };
    void refresh();
    return () => {
      alive = false;
      controller.abort();
      clearTimeout(timer);
    };
  }, [scanId, revision]);
  const jobs = queue?.jobs.filter((job) => job.scanId === scanId) || [];
  async function mutate(id?: string) {
    setBusy(true);
    setError('');
    try {
      await api(id ? `/api/reconstruction/${id}` : '/api/reconstruction', {
        method: id ? 'DELETE' : 'POST',
        body: JSON.stringify(id ? {} : { scanId }),
      });
      setRevision((value) => value + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('La demande a échoué.'));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="form-stack" aria-label={t('Reconstruction de cette série')}>
      <h3>{t('Le prochain point de vue.')}</h3>
      {queue && !queue.workerAvailable && (
        <p className="field-hint">
          {' '}
          {t(
            'Le calcul 3D est actuellement indisponible. Vos photos restent conservées et exportables.',
          )}{' '}
        </p>
      )}
      {queue?.workerAvailable && jobs.length === 0 && (
        <>
          <p className="field-hint">
            {' '}
            {t(
              'Lancez le calcul sur cette série finalisée, avec un maximum de 24 photos. Le résultat devra être vérifié avant publication.',
            )}{' '}
          </p>
          <button className="button button-blue" disabled={busy} onClick={() => void mutate()}>
            {' '}
            {t('Lancer la reconstruction')}{' '}
          </button>
        </>
      )}
      {jobs.map((job) => (
        <div className="notice" key={job.id}>
          <strong>{t(labels[job.state] || job.state)}</strong>
          {job.state === 'running' && (
            <p>{t('Le moteur traite les photos. Aucune durée restante n’est estimée.')}</p>
          )}
          {job.state === 'ready_for_review' && (
            <p>
              {' '}
              {t(
                'Les fichiers sont prêts sur la machine de calcul. Vérifiez le modèle et ses textures avant de l’importer dans la fiche du plat.',
              )}{' '}
            </p>
          )}
          {['failed', 'cancelled'].includes(job.state) && (
            <p>{t('Vos originaux et le modèle précédent sont conservés.')}</p>
          )}
          {['queued', 'running'].includes(job.state) && (
            <button className="text-button" disabled={busy} onClick={() => void mutate(job.id)}>
              {' '}
              {t('Annuler le calcul')}{' '}
            </button>
          )}
        </div>
      ))}
      {error && (
        <p className="notice notice-error" role="alert">
          {t(error)}
        </p>
      )}
    </section>
  );
}
