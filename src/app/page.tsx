import Link from 'next/link';
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

export default function Home() {
  return (
    <>
      <Header />
      <main id="main">
        <section className="hero container">
          <div className="hero-copy">
            <p className="eyebrow">
              <span className="tiny-dot" /> LE MENU PREND UNE AUTRE DIMENSION
            </p>
            <h1>
              On mange aussi
              <br />
              avec <span>les yeux.</span>
            </h1>
            <p className="hero-description">
              Votre cuisine mérite mieux qu’une ligne sur une carte. Donnez à vos clients un
              avant-goût de ce qui les attend.
            </p>
            <div className="hero-actions">
              <Link className="button button-blue" href="/signup">
                Créer ma carte <ArrowUpRight size={19} />
              </Link>
              <Link className="text-button" href="/menu/demo">
                <CirclePlay size={21} /> Explorer le menu démo
              </Link>
            </div>
            <p className="hero-note">
              <Check size={15} /> Un QR. Votre carte. Sans application à installer.
            </p>
          </div>
          <div className="hero-visual">
            <div className="hero-photo">
              <img
                src="/images/burger.jpg"
                alt="Un burger photographié, exemple de présentation d’un plat"
                fetchPriority="high"
                width="900"
                height="1100"
              />
              <div className="photo-shade" />
              <span className="photo-label">
                <span className="tiny-dot" /> PHOTOGRAPHIE D’ILLUSTRATION
              </span>
              <div className="hero-photo-title">
                <span>Le goût commence ici.</span>
                <p>
                  Une nouvelle façon
                  <br />
                  de découvrir la carte.
                </p>
              </div>
              <div className="visual-index">
                <span>01 — 03</span>
                <span>CAPTURER · PUBLIER · DÉCOUVRIR</span>
              </div>
            </div>
            <Link className="floating-menu" href="/menu/demo">
              <div className="floating-menu-icon">
                <QrCode size={30} />
              </div>
              <div>
                <span>À découvrir à table</span>
                <strong>Votre prochain coup de cœur</strong>
              </div>
              <ArrowUpRight size={21} />
            </Link>
          </div>
          <a href="#comment-ca-marche" className="scroll-cue">
            <ArrowDown size={16} /> La suite se savoure
          </a>
        </section>
        <div className="feature-strip">
          <div className="container">
            <span>
              <Smartphone size={19} /> Accessible depuis un QR
            </span>
            <span>
              <Camera size={19} /> Vos vrais plats en photo
            </span>
            <span>
              <Layers3 size={19} /> Des modèles 3D réutilisables
            </span>
            <span>
              <Check size={19} /> Une carte qui vous appartient
            </span>
          </div>
        </div>
        <section id="comment-ca-marche" className="section container">
          <div className="section-heading">
            <div>
              <p className="eyebrow">DE VOTRE CUISINE À LEUR ÉCRAN</p>
              <h2>
                Trois étapes.
                <br />
                Tout un nouvel appétit.
              </h2>
            </div>
            <p>
              Vous créez, vous ajustez, vous partagez.
              <br />
              Vos clients n’ont plus qu’à découvrir.
            </p>
          </div>
          <div className="steps-grid">
            <article className="step-card">
              <span className="step-number">01 / CAPTURER</span>
              <div className="step-icon">
                <Camera size={32} />
              </div>
              <h3>Le plat, sous son meilleur jour.</h3>
              <p>
                Importez une photo ou ouvrez la capture guidée. Vos prises restent sur votre
                appareil et peuvent être exportées.
              </p>
              <Link href="/capture" className="inline-link">
                Ouvrir la capture <ArrowUpRight size={16} />
              </Link>
            </article>
            <article className="step-card">
              <span className="step-number">02 / PUBLIER</span>
              <div className="step-icon">
                <Layers3 size={32} />
              </div>
              <h3>Une carte bien à vous.</h3>
              <p>
                Organisez vos plats, renseignez prix et allergènes, puis publiez. Votre QR reste le
                même quand la carte évolue.
              </p>
              <Link href="/signup" className="inline-link">
                Créer mon espace <ArrowUpRight size={16} />
              </Link>
            </article>
            <article className="step-card">
              <span className="step-number">03 / DÉCOUVRIR</span>
              <div className="step-icon">
                <QrCode size={32} />
              </div>
              <h3>Un scan. Et l’envie vient.</h3>
              <p>
                Un menu photo sans compte. Les modèles 3D importés se découvrent à la demande, avec
                AR sur appareil compatible.
              </p>
              <Link href="/menu/demo" className="inline-link">
                Voir un exemple <ArrowUpRight size={16} />
              </Link>
            </article>
          </div>
        </section>
        <section className="showcase-section">
          <div className="container showcase-grid">
            <div className="showcase-copy">
              <p className="eyebrow">LA CARTE, EN PLUS VIVANT</p>
              <h2>
                Laissez vos plats
                <br />
                faire les
                <br />
                <span>présentations.</span>
              </h2>
              <p>
                Des photos généreuses, des informations claires et le temps de choisir. Une
                expérience pensée pour le plaisir de passer à table.
              </p>
              <Link href="/menu/demo" className="button button-white">
                S’installer à la table démo <ArrowRight size={18} />
              </Link>
              <p className="showcase-disclaimer">
                Carte illustrative. Aucun modèle de plat reconstruit n’est présenté dans cette
                démonstration.
              </p>
            </div>
            <div className="menu-preview">
              <div className="preview-top">
                <Brand />
                <span>EXEMPLE DE MENU</span>
              </div>
              <img
                className="preview-image"
                src="/images/pasta.jpg"
                alt="Photographie illustrative d’un plat de pâtes"
                loading="lazy"
                width="700"
                height="500"
              />
              <div className="preview-body">
                <span className="eyebrow">LES PLATS · FAIT POUR ÊTRE DÉCOUVERT</span>
                <div>
                  <h3>Pasta della casa</h3>
                  <strong>22,00 €</strong>
                </div>
                <p>Pâtes, tomates et herbes fraîches.</p>
                <Link href="/menu/demo" className="preview-link">
                  Découvrir la carte <ArrowUpRight size={18} />
                </Link>
              </div>
            </div>
          </div>
        </section>
        <section className="section container clarity-section">
          <p className="eyebrow">PENSÉ POUR LE QUOTIDIEN</p>
          <h2>
            La carte change.
            <br />
            Le lien reste.
          </h2>
          <div className="clarity-grid">
            <div>
              <span>01</span>
              <h3>La main sur votre menu</h3>
              <p>
                Un plat du jour, un nouveau prix ou une rupture ? Préparez vos modifications et
                choisissez quand les publier.
              </p>
            </div>
            <div>
              <span>02</span>
              <h3>La photo, toujours disponible</h3>
              <p>
                La carte reste consultable sans caméra. Si la 3D n’est pas disponible, la photo et
                les informations prennent le relais.
              </p>
            </div>
            <div>
              <span>03</span>
              <h3>La 3D, quand elle est prête</h3>
              <p>
                Importez vos exports GLB et USDZ validés. La reconstruction demande un moteur séparé
                ; la capture web conserve vos photos.
              </p>
            </div>
          </div>
        </section>
        <section className="closing-section container">
          <div>
            <p className="eyebrow">À VOUS DE DRESSER LA CARTE</p>
            <h2>
              Et si on commençait
              <br />
              par votre premier plat ?
            </h2>
          </div>
          <Link href="/signup" className="button button-blue">
            Créer mon espace restaurant <ArrowUpRight size={20} />
          </Link>
        </section>
      </main>
      <Footer />
    </>
  );
}
