import { createTranslator, isLocale } from '@/lib/i18n';
import { LocalizedLink as Link } from '@/components/language';
import {
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  Camera,
  Check,
  CirclePlay,
  Layers3,
  QrCode,
  Smartphone,
} from 'lucide-react';
import { Brand, Footer, Header } from '@/components/brand';

export default async function Home({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  const t = createTranslator(isLocale(locale) ? locale : 'fr');
  return (
    <>
      <Header />
      <main id="main">
        <section className="hero container">
          <div className="hero-copy">
            <p className="eyebrow">
              <span className="tiny-dot" /> {t('LE MENU PREND UNE AUTRE DIMENSION')}{' '}
            </p>
            <h1>
              {' '}
              {t('On mange aussi')} <br /> {t('avec')} <span>{t('les yeux.')}</span>
            </h1>
            <p className="hero-description">
              {' '}
              {t(
                'Votre cuisine mérite mieux qu’une ligne sur une carte. Donnez à vos clients un avant-goût de ce qui les attend.',
              )}{' '}
            </p>
            <div className="hero-actions">
              <Link className="button button-blue" href="/signup">
                {' '}
                {t('Créer ma carte')} <ArrowUpRight size={19} />
              </Link>
              <Link className="text-button" href="/menu/demo">
                <CirclePlay size={21} /> {t('Explorer le menu démo')}{' '}
              </Link>
            </div>
            <p className="hero-note">
              <Check size={15} /> {t('Un QR. Votre carte. Sans application à installer.')}{' '}
            </p>
          </div>
          <div className="hero-visual">
            <div className="hero-photo">
              <img
                src="/images/burger.jpg"
                alt={t('Un burger photographié, exemple de présentation d’un plat')}
                fetchPriority="high"
                width="900"
                height="1100"
              />
              <div className="photo-shade" />
              <span className="photo-label">
                <span className="tiny-dot" /> {t('PHOTOGRAPHIE D’ILLUSTRATION')}{' '}
              </span>
              <div className="hero-photo-title">
                <span>{t('Le goût commence ici.')}</span>
                <p>
                  {' '}
                  {t('Une nouvelle façon')} <br /> {t('de découvrir la carte.')}{' '}
                </p>
              </div>
              <div className="visual-index">
                <span>01 — 03</span>
                <span>{t('CAPTURER · PUBLIER · DÉCOUVRIR')}</span>
              </div>
            </div>
            <Link className="floating-menu" href="/menu/demo">
              <div className="floating-menu-icon">
                <QrCode size={30} />
              </div>
              <div>
                <span>{t('À découvrir à table')}</span>
                <strong>{t('Votre prochain coup de cœur')}</strong>
              </div>
              <ArrowUpRight size={21} />
            </Link>
          </div>
          <a href="#comment-ca-marche" className="scroll-cue">
            <ArrowDown size={16} /> {t('La suite se savoure')}{' '}
          </a>
        </section>
        <div className="feature-strip">
          <div className="container">
            <span>
              <Smartphone size={19} /> {t('Accessible depuis un QR')}{' '}
            </span>
            <span>
              <Camera size={19} /> {t('Vos vrais plats en photo')}{' '}
            </span>
            <span>
              <Layers3 size={19} /> {t('Des modèles 3D réutilisables')}{' '}
            </span>
            <span>
              <Check size={19} /> {t('Une carte qui vous appartient')}{' '}
            </span>
          </div>
        </div>
        <section id="comment-ca-marche" className="section container">
          <div className="section-heading">
            <div>
              <p className="eyebrow">{t('DE VOTRE CUISINE À LEUR ÉCRAN')}</p>
              <h2>
                {' '}
                {t('Trois étapes.')} <br /> {t('Tout un nouvel appétit.')}{' '}
              </h2>
            </div>
            <p>
              {' '}
              {t('Vous créez, vous ajustez, vous partagez.')} <br />{' '}
              {t('Vos clients n’ont plus qu’à découvrir.')}{' '}
            </p>
          </div>
          <div className="steps-grid">
            <article className="step-card">
              <span className="step-number">{t('01 / CAPTURER')}</span>
              <div className="step-icon">
                <Camera size={32} />
              </div>
              <h3>{t('Le plat, sous son meilleur jour.')}</h3>
              <p>
                {' '}
                {t(
                  'Importez une photo ou ouvrez la capture guidée. Vos prises restent sur votre appareil et peuvent être exportées.',
                )}{' '}
              </p>
              <Link href="/capture" className="inline-link">
                {' '}
                {t('Ouvrir la capture')} <ArrowUpRight size={16} />
              </Link>
            </article>
            <article className="step-card">
              <span className="step-number">{t('02 / PUBLIER')}</span>
              <div className="step-icon">
                <Layers3 size={32} />
              </div>
              <h3>{t('Une carte bien à vous.')}</h3>
              <p>
                {' '}
                {t(
                  'Organisez vos plats, renseignez prix et allergènes, puis publiez. Votre QR reste le même quand la carte évolue.',
                )}{' '}
              </p>
              <Link href="/signup" className="inline-link">
                {' '}
                {t('Créer mon espace')} <ArrowUpRight size={16} />
              </Link>
            </article>
            <article className="step-card">
              <span className="step-number">{t('03 / DÉCOUVRIR')}</span>
              <div className="step-icon">
                <QrCode size={32} />
              </div>
              <h3>{t('Un scan. Et l’envie vient.')}</h3>
              <p>
                {' '}
                {t(
                  'Un menu photo sans compte. Les modèles 3D importés se découvrent à la demande, avec AR sur appareil compatible.',
                )}{' '}
              </p>
              <Link href="/menu/demo" className="inline-link">
                {' '}
                {t('Voir un exemple')} <ArrowUpRight size={16} />
              </Link>
            </article>
          </div>
        </section>
        <section className="showcase-section">
          <div className="container showcase-grid">
            <div className="showcase-copy">
              <p className="eyebrow">{t('LA CARTE, EN PLUS VIVANT')}</p>
              <h2>
                {' '}
                {t('Laissez vos plats')} <br /> {t('faire les')} <br />
                <span>{t('présentations.')}</span>
              </h2>
              <p>
                {' '}
                {t(
                  'Des photos généreuses, des informations claires et le temps de choisir. Une expérience pensée pour le plaisir de passer à table.',
                )}{' '}
              </p>
              <Link href="/menu/demo" className="button button-white">
                {' '}
                {t('S’installer à la table démo')} <ArrowRight size={18} />
              </Link>
              <p className="showcase-disclaimer">
                {' '}
                {t(
                  'Carte illustrative. Aucun modèle de plat reconstruit n’est présenté dans cette démonstration.',
                )}{' '}
              </p>
            </div>
            <div className="menu-preview">
              <div className="preview-top">
                <Brand />
                <span>{t('EXEMPLE DE MENU')}</span>
              </div>
              <img
                className="preview-image"
                src="/images/pasta.jpg"
                alt={t('Photographie illustrative d’un plat de pâtes')}
                loading="lazy"
                width="700"
                height="500"
              />
              <div className="preview-body">
                <span className="eyebrow">{t('LES PLATS · FAIT POUR ÊTRE DÉCOUVERT')}</span>
                <div>
                  <h3>Pasta della casa</h3>
                  <strong>{t('22,00 €')}</strong>
                </div>
                <p>{t('Pâtes, tomates et herbes fraîches.')}</p>
                <Link href="/menu/demo" className="preview-link">
                  {' '}
                  {t('Découvrir la carte')} <ArrowUpRight size={18} />
                </Link>
              </div>
            </div>
          </div>
        </section>
        <section className="section container clarity-section">
          <p className="eyebrow">{t('PENSÉ POUR LE QUOTIDIEN')}</p>
          <h2>
            {' '}
            {t('La carte change.')} <br /> {t('Le lien reste.')}{' '}
          </h2>
          <div className="clarity-grid">
            <div>
              <span>01</span>
              <h3>{t('La main sur votre menu')}</h3>
              <p>
                {' '}
                {t(
                  'Un plat du jour, un nouveau prix ou une rupture ? Préparez vos modifications et choisissez quand les publier.',
                )}{' '}
              </p>
            </div>
            <div>
              <span>02</span>
              <h3>{t('La photo, toujours disponible')}</h3>
              <p>
                {' '}
                {t(
                  'La carte reste consultable sans caméra. Si la 3D n’est pas disponible, la photo et les informations prennent le relais.',
                )}{' '}
              </p>
            </div>
            <div>
              <span>03</span>
              <h3>{t('La 3D, quand elle est prête')}</h3>
              <p>
                {' '}
                {t(
                  'Importez vos exports GLB et USDZ validés. La reconstruction demande un moteur séparé ; la capture web conserve vos photos.',
                )}{' '}
              </p>
            </div>
          </div>
        </section>
        <section className="closing-section container">
          <div>
            <p className="eyebrow">{t('À VOUS DE DRESSER LA CARTE')}</p>
            <h2>
              {' '}
              {t('Et si on commençait')} <br /> {t('par votre premier plat ?')}{' '}
            </h2>
          </div>
          <Link href="/signup" className="button button-blue">
            {' '}
            {t('Créer mon espace restaurant')} <ArrowUpRight size={20} />
          </Link>
        </section>
      </main>
      <Footer />
    </>
  );
}
