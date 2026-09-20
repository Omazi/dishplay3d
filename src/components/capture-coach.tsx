'use client';
import { ArrowRight, Check, RotateCw, Smartphone, Utensils, MoveUpRight } from 'lucide-react';
import { useI18n } from './language';
import { capturePasses } from '@/lib/capture-quality';
import type { CaptureFrame } from './capture-store';

// Instructional diagram: selected height, not a tracked phone position.
export function CaptureDiagram({ pass, compact = false }: { pass: number; compact?: boolean }) {
  const { t } = useI18n();
  return (
    <div
      className={`capture-diagram ${compact ? 'is-compact' : ''}`}
      data-pass={pass}
      role="img"
      aria-label={t(
        'Schéma du mouvement conseillé : tournez autour du plat à {0}, sans déplacer l’assiette.',
        [capturePasses[pass].angle],
      )}
    >
      <div className="diagram-orbit" aria-hidden="true">
        <RotateCw size={132} strokeWidth={0.7} />
      </div>
      <div className="diagram-dish" aria-hidden="true">
        <Utensils size={23} />
      </div>
      <div className="diagram-phone" aria-hidden="true">
        <Smartphone size={31} />
        <span>{capturePasses[pass].angle}</span>
      </div>
      <span className="diagram-label">{t('Le plat reste immobile')}</span>
      <span className="diagram-caption">{t('Mouvement conseillé')}</span>
    </div>
  );
}

export function CaptureCoach({
  pass,
  completed,
  frames,
  disabled,
  live,
  onChange,
}: {
  pass: number;
  completed: boolean[];
  frames: CaptureFrame[];
  disabled: boolean;
  live: boolean;
  onChange: (pass: number, completed: boolean[]) => void;
}) {
  const { t } = useI18n();
  const count = frames.filter(
    (f) => f.capture?.source === 'camera' && f.capture.pass === pass,
  ).length;
  const guide = capturePasses[pass];
  return (
    <section className="capture-coach" aria-label={t('Votre parcours de capture')}>
      <div className="coach-intro">
        <span className="eyebrow">{t('3 PASSAGES AUTOUR DU PLAT')}</span>
        <span>{t('À votre rythme')}</span>
      </div>
      <div className="pass-selector" aria-label={t('Choisir le passage')}>
        {capturePasses.map((p, index) => (
          <button
            type="button"
            key={p.name}
            aria-pressed={index === pass}
            disabled={disabled}
            onClick={() => onChange(index, completed)}
          >
            <span>{completed[index] ? <Check size={16} /> : `0${index + 1}`}</span>
            <strong>{t(p.name)}</strong>
            <small>{p.angle}</small>
          </button>
        ))}
      </div>
      <details className="coach-details" open={!live}>
        <summary>{t(guide.short)}</summary>
        <div className="coach-body">
          <CaptureDiagram pass={pass} />
          <div className="coach-copy">
            <p className="eyebrow">{t('PASSAGE {0} / 3', [pass + 1])}</p>
            <h2>{t(guide.title)}</h2>
            <p>{t(guide.instruction)}</p>
            <p className="coach-rhythm">
              <MoveUpRight size={17} />
              {t(
                'Un petit pas, une pause, une photo. Gardez une grande partie de la vue précédente dans la suivante.',
              )}
            </p>
            <div className="coach-count">
              <strong>{t('Photos dans ce passage : {0}', [count])}</strong>
              <span>{t('Repère de départ : environ 30 vues par tour, à adapter au plat.')}</span>
            </div>
            <button
              className="inline-link"
              disabled={disabled || count === 0}
              onClick={() => {
                const next = [...completed];
                next[pass] = !next[pass];
                onChange(next[pass] ? Math.min(2, pass + 1) : pass, next);
              }}
            >
              {completed[pass] ? t('Reprendre ce passage') : t('J’ai fait tout le tour')}{' '}
              {completed[pass] ? <RotateCw size={16} /> : <ArrowRight size={16} />}
            </button>
            <p className="coach-disclaimer">
              {t(
                'Vous confirmez le tour vous-même. Ce schéma ne suit pas votre position et le nombre de photos ne mesure pas la couverture 3D.',
              )}
            </p>
          </div>
        </div>
      </details>
      {completed.every(Boolean) && (
        <p className="coach-finished">
          <Check size={18} />
          {t(
            'Vos trois passages sont cochés. Revoyez les photos et ajoutez les angles manquants avant le transfert.',
          )}
        </p>
      )}
    </section>
  );
}
