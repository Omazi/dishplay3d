import { createTranslator, isLocale } from '@/lib/i18n';
import { LocalizedLink as Link } from '@/components/language';
import {
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  Check,
  Camera,
  Layers3,
  QrCode,
  Plus,
} from 'lucide-react';
import { Footer, Header } from '@/components/brand';
import { ProductStory, RevealMotion } from '@/components/product-story';
import QRCode from 'qrcode';
import '../premium.css';

export default async function Home({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  const t = createTranslator(isLocale(locale) ? locale : 'fr');
  const qr = await QRCode.toDataURL(
    `https://dishplay3d.vercel.app${locale === 'en' ? '/en' : ''}/menu/demo`,
    { width: 256, margin: 2, color: { dark: '#252824', light: '#ffffff' } },
  );
  return (
    <div className="premium-site">
      <Header />
      <RevealMotion />
      <main id="main">
        <section className="premium-hero">
          <div className="container premium-hero-copy">
            <p className="eyebrow">
              <span className="tiny-dot" />
              {t('VOTRE CARTE. UNE NOUVELLE DIMENSION.')}
            </p>
            <h1>
              {t('Le goût.')}
              <br />
              <span>{t('Sous un nouvel angle.')}</span>
            </h1>
            <p className="premium-hero-description">
              {t('Faites découvrir vos plats avant la première bouchée.')}
              <br />
              {t('De votre cuisine à leur écran, avec DishPlay.')}
            </p>
            <div className="premium-actions">
              <Link className="button button-blue" href="/signup">
                {t('Créer ma carte')}
                <ArrowUpRight size={18} />
              </Link>
              <a className="text-button" href="#comment-ca-marche">
                {t('Voir comment ça marche')}
                <ArrowDown size={17} />
              </a>
            </div>
          </div>
          <div className="premium-food-gallery" aria-label={t('Photographies de présentation')}>
            <figure className="food-side food-left">
              <img
                src="/images/salad.jpg"
                width="700"
                height="900"
                alt={t('Une salade, photographie d’illustration')}
              />
              <figcaption>03 / {t('La fraîcheur.')}</figcaption>
            </figure>
            <figure className="food-main">
              <img
                src="/images/burger.jpg"
                width="900"
                height="1100"
                fetchPriority="high"
                alt={t('Un burger photographié, exemple de présentation d’un plat')}
              />
              <figcaption>
                <span>{t('Le goût commence ici.')}</span>
                <strong>{t('L’envie se voit.')}</strong>
                <span>{t('PHOTOGRAPHIE D’ILLUSTRATION')}</span>
              </figcaption>
            </figure>
            <figure className="food-side food-right">
              <img
                src="/images/pasta.jpg"
                width="700"
                height="900"
                alt={t('Photographie illustrative d’un plat de pâtes')}
              />
              <figcaption>02 / {t('Le savoir-faire.')}</figcaption>
            </figure>
          </div>
          <div className="premium-proof container">
            <span>
              <Camera size={18} />
              {t('Vos vrais plats')}
            </span>
            <span>
              <QrCode size={18} />
              {t('Un QR toujours valable')}
            </span>
            <span>
              <Check size={18} />
              {t('Sans app pour vos clients')}
            </span>
          </div>
        </section>
        <section className="premium-manifesto container" data-reveal>
          <p className="eyebrow">{t('VOUS CUISINEZ. DISHPLAY DONNE À VOIR.')}</p>
          <h2>
            {t('Une carte raconte.')}
            <br />
            <span>{t('La vôtre donne envie.')}</span>
          </h2>
          <p>
            {t(
              'La texture d’un pain. Le détail d’un dressage. La générosité d’une assiette. Donnez à chaque plat la place qu’il mérite, avec une carte aussi soignée que votre cuisine.',
            )}
          </p>
        </section>
        <ProductStory qr={qr} />
        <section className="premium-capture-section">
          <div className="container premium-capture-layout">
            <div data-reveal>
              <p className="eyebrow">{t('LA CAPTURE, EN CLAIR')}</p>
              <h2>
                {t('Vous bougez.')}
                <br />
                <span>{t('Le plat reste.')}</span>
              </h2>
              <p>
                {t(
                  'Trois hauteurs. Des petits pas. Une pause à chaque vue. Le guide vous accompagne sans vous demander de deviner la suite.',
                )}
              </p>
              <Link className="button button-white" href="/capture">
                {t('Ouvrir la capture guidée')}
                <ArrowUpRight size={18} />
              </Link>
            </div>
            <div className="premium-capture-steps" data-reveal>
              {[
                [
                  '01',
                  'Préparez la scène.',
                  'Une lumière douce, une assiette immobile et la place de faire le tour.',
                ],
                [
                  '02',
                  'Tournez. Faites une pause.',
                  'Gardez le plat entier dans le cadre. La lumière, la stabilité et les détails de l’image vous donnent des repères.',
                ],
                [
                  '03',
                  'Montez. Puis recommencez.',
                  'Capturez les côtés, les reliefs, puis le dessus. Revoyez les prises signalées avant de transférer votre série.',
                ],
              ].map(([number, title, description]) => (
                <article key={number}>
                  <span>{number}</span>
                  <div>
                    <h3>{t(title)}</h3>
                    <p>{t(description)}</p>
                  </div>
                </article>
              ))}
            </div>
          </div>
        </section>
        <section className="premium-real container">
          <div className="premium-section-heading" data-reveal>
            <p className="eyebrow">{t('UNE BELLE EXPÉRIENCE. DES REPÈRES CLAIRS.')}</p>
            <h2>
              {t('La photo aujourd’hui.')}
              <br />
              <span>{t('La 3D, quand elle est prête.')}</span>
            </h2>
          </div>
          <div className="premium-real-grid">
            <article data-reveal>
              <Camera size={26} />
              <h3>{t('Votre carte peut déjà vivre.')}</h3>
              <p>
                {t(
                  'Une photo suffit pour publier un plat. Ajoutez prix, description et allergènes, partagez le QR et faites évoluer votre carte à votre rythme.',
                )}
              </p>
            </article>
            <article data-reveal>
              <Layers3 size={26} />
              <h3>{t('Un modèle, une étape en plus.')}</h3>
              <p>
                {t(
                  'Une série de photos ne devient pas automatiquement un modèle 3D. La reconstruction est séparée. Vous pouvez aussi importer un modèle GLB/USDZ validé et le proposer sur votre carte.',
                )}
              </p>
            </article>
          </div>
          <div className="premium-faq">
            {[
              [
                'Le guide web reproduit-il le cube et les points 3D ?',
                'Le navigateur propose des photos guidées et des indices sur l’image. Le volume ancré et les points spatiaux appartiennent au parcours de capture native, à valider sur un appareil compatible. Le guide web ne mesure pas votre couverture 3D.',
              ],
              [
                'Mes clients doivent-ils installer une application ?',
                'Non. Le QR ouvre le menu dans leur navigateur, sans compte. Les photos restent disponibles ; l’affichage en réalité augmentée dépend du modèle et de l’appareil.',
              ],
              [
                'Le QR change-t-il quand je change un prix ?',
                'Non. Préparez vos modifications puis publiez-les : le lien du restaurant et le QR restent identiques.',
              ],
            ].map(([question, answer]) => (
              <details key={question}>
                <summary>
                  {t(question)}
                  <Plus size={18} />
                </summary>
                <p>{t(answer)}</p>
              </details>
            ))}
          </div>
        </section>
        <section className="premium-closing container" data-reveal>
          <p className="eyebrow">{t('VOTRE PROCHAIN CHAPITRE')}</p>
          <h2>
            {t('À vous de')}
            <br />
            <span>{t('donner envie.')}</span>
          </h2>
          <Link href="/signup" className="button button-blue">
            {t('Créer mon espace restaurant')}
            <ArrowRight size={18} />
          </Link>
          <Link href="/menu/demo" className="inline-link">
            {t('Explorer le menu démo')}
            <ArrowUpRight size={16} />
          </Link>
        </section>
      </main>
      <Footer />
    </div>
  );
}
