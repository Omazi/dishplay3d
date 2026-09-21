import type { ReactNode } from 'react';
import Link from 'next/link';
import { ArrowUpRight, ArrowRight } from 'lucide-react';
import type { Dish } from '@/lib/contracts';
import type { LandingCopy } from './content';
function Title({ lines, hero = false }: { lines: string[]; hero?: boolean }) {
  const Tag = hero ? 'h1' : 'h2';
  return (
    <Tag tabIndex={-1}>
      {lines[0]}
      <br />
      <span>{lines[1]}</span>
    </Tag>
  );
}
function StaticDish({ copy }: { copy: LandingCopy }) {
  return (
    <img
      className="launch-static-dish"
      src="/images/burger-story.webp"
      width="700"
      height="700"
      alt={copy.poster}
      loading="lazy"
    />
  );
}

export function Arrival({ c, path }: { c: LandingCopy; path: (href: string) => string }) {
  return (
    <section className="launch-scene launch-intro" id="arrivee" aria-label={c.chapterLabels[0]}>
      <div className="launch-copy">
        <p className="launch-kicker">{c.eyebrow}</p>
        <Title lines={c.hero} hero />
        <p className="launch-description">{c.intro}</p>
        <div className="launch-actions">
          <Link className="launch-primary" href={path('/menu/demo')}>
            {c.discover}
            <ArrowUpRight size={17} />
          </Link>
          <Link className="launch-text-link" href={path('/signup')}>
            {c.navCreate}
            <ArrowRight size={17} />
          </Link>
        </div>
      </div>
      <StaticDish copy={c} />
    </section>
  );
}

export function Exploration({ c, demoLink }: { c: LandingCopy; demoLink: ReactNode }) {
  return (
    <section
      className="launch-scene launch-exploration"
      id="experience-3d"
      aria-label={c.chapterLabels[1]}
    >
      <div className="launch-copy">
        <p className="launch-kicker">01 / {c.chapterLabels[1]}</p>
        <Title lines={c.details} />
        <p className="launch-description">{c.detailText}</p>
        <button className="launch-text-link launch-explore" data-explore="1">
          {c.explore}
          <ArrowUpRight size={17} />
        </button>
        <span className="launch-static-link">{demoLink}</span>
      </div>
      <StaticDish copy={c} />
    </section>
  );
}

export function MenuReveal({
  c,
  demoLink,
  qr,
  demoUrl,
  dish,
  price,
}: {
  c: LandingCopy;
  demoLink: ReactNode;
  qr: string;
  demoUrl: string;
  dish: Dish;
  price: string;
}) {
  return (
    <section
      className="launch-scene launch-menu-scene"
      id="menu-reveal"
      aria-label={c.chapterLabels[2]}
    >
      <div className="launch-copy">
        <p className="launch-kicker">02 / {c.chapterLabels[2]}</p>
        <Title lines={c.menuTitle} />
        <p className="launch-description">{c.menuText}</p>
        {demoLink}
        <a className="launch-qr" href={demoUrl} aria-label={c.qr}>
          <img src={qr} width="88" height="88" alt="QR" data-destination={demoUrl} />
          <span>{c.qr}</span>
        </a>
      </div>
      <div className="launch-static-card">
        <StaticDish copy={c} />
        <h3>
          {dish.name} <span>{price}</span>
        </h3>
        <p>{dish.description}</p>
        <small>{c.menuCaption}</small>
      </div>
    </section>
  );
}

export function TableScene({ c, demoLink }: { c: LandingCopy; demoLink: ReactNode }) {
  return (
    <section
      className="launch-scene launch-table-scene"
      id="sur-table"
      aria-label={c.chapterLabels[3]}
    >
      <div className="launch-copy">
        <p className="launch-kicker">03 / {c.chapterLabels[3]}</p>
        <Title lines={c.tableTitle} />
        <p className="launch-description">{c.tableText}</p>
        {demoLink}
        <p className="launch-caption">{c.tableCaption}</p>
      </div>
      <div className="launch-static-table">
        <StaticDish copy={c} />
      </div>
    </section>
  );
}

export function CreatorJourney({
  c,
  path,
  locale,
  dish,
}: {
  c: LandingCopy;
  path: (href: string) => string;
  locale: string;
  dish: Dish;
}) {
  return (
    <section className="launch-creator" id="comment-ca-marche">
      <div className="launch-creator-heading">
        <p className="launch-kicker">{c.creatorEyebrow}</p>
        <Title lines={c.creatorTitle} />
        <p>{c.creatorText}</p>
        <Link className="launch-text-link" href={path('/capture')}>
          {c.capture}
          <ArrowUpRight size={17} />
        </Link>
      </div>
      <div className="launch-workflow">
        <figure className="launch-kitchen">
          <img src="/images/burger.jpg" width="800" height="1000" alt={dish.name} loading="lazy" />
          <figcaption>
            {locale === 'fr'
              ? 'Une photographie pour commencer. La 3D pour aller plus loin.'
              : 'Start with a photograph. Go further with 3D.'}
          </figcaption>
        </figure>
        <ol>
          {c.steps.map(([title, text], index) => (
            <li key={title}>
              <span>0{index + 1}</span>
              <div>
                <h3>{title}</h3>
                <p>{text}</p>
              </div>
            </li>
          ))}
        </ol>
      </div>
      <figure className="launch-capture-evidence">
        <img
          src={`/images/capture-guide-${locale}.webp`}
          width="928"
          height="548"
          loading="lazy"
          alt={
            locale === 'fr'
              ? 'Le guide de capture DishPlay : trois passages autour du plat, sans caméra ouverte.'
              : 'The DishPlay capture guide: three passes around the dish, with no camera open.'
          }
        />
        <figcaption>
          {locale === 'fr'
            ? 'Capture réelle du guide web. Le schéma explique le mouvement ; il ne mesure pas une reconstruction en direct.'
            : 'Actual web guide screenshot. The diagram explains movement; it does not measure live reconstruction.'}
        </figcaption>
      </figure>
      <p className="launch-workflow-caption">{c.workflowCaption}</p>
    </section>
  );
}

export function LandingFAQ({ c }: { c: LandingCopy }) {
  return (
    <section className="launch-faq">
      <h2>{c.faqTitle}</h2>
      <div>
        {c.faqs.map(([q, a]) => (
          <details key={q}>
            <summary>
              {q}
              <span aria-hidden="true">+</span>
            </summary>
            <p>{a}</p>
          </details>
        ))}
      </div>
    </section>
  );
}

export function Conclusion({
  c,
  path,
  demoLink,
}: {
  c: LandingCopy;
  path: (href: string) => string;
  demoLink: ReactNode;
}) {
  return (
    <section className="launch-end">
      <p className="launch-kicker">DISHPLAY</p>
      <Title lines={c.end} />
      <p>{c.endText}</p>
      <Link className="launch-primary" href={path('/signup')}>
        {c.navCreate}
        <ArrowUpRight size={18} />
      </Link>
      {demoLink}
    </section>
  );
}
