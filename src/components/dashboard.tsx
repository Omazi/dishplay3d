'use client';

import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  ArrowUpRight,
  Camera,
  Check,
  CheckCircle2,
  ChevronRight,
  Download,
  ExternalLink,
  Eye,
  ImageIcon,
  LayoutGrid,
  LoaderCircle,
  LogOut,
  MoreHorizontal,
  Plus,
  Printer,
  QrCode,
  Save,
  Search,
  Settings2,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
import type { Category, Dish, RestaurantWorkspace } from '@/lib/contracts';
import { dishImageUrl } from '@/lib/demo';
import { api, ApiClientError, formatPrice } from './api-client';
import { Brand } from './brand';
import { MenuView } from './menu-view';

const emptyDish = {
  name: '',
  description: '',
  priceCents: 0,
  categoryId: null,
  allergens: [],
  imageId: null,
  isAvailable: true,
  sortOrder: 0,
  modelGlbUrl: null,
  modelUsdzUrl: null,
};

function DishEditor({
  dish,
  categories,
  onClose,
  onSaved,
}: {
  dish: Dish | null;
  categories: Category[];
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const modal = useRef<HTMLDialogElement>(null);
  const photoInput = useRef<HTMLInputElement>(null);
  const [imageId, setImageId] = useState(dish?.imageId || null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [deletePrompt, setDeletePrompt] = useState(false);
  const source = dish || emptyDish;
  useEffect(() => {
    modal.current?.showModal();
  }, []);
  async function upload(file?: File) {
    if (!file) return;
    if (
      !['image/jpeg', 'image/png', 'image/webp'].includes(file.type) ||
      file.size > 3 * 1024 * 1024
    ) {
      setError('Choisissez une photo JPEG, PNG ou WebP de 3 Mo maximum.');
      return;
    }
    setUploading(true);
    setError('');
    try {
      const result = await api<{ id: string }>('/api/media', {
        method: 'POST',
        body: file,
        headers: { 'Content-Type': file.type },
      });
      setImageId(result.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Import impossible.');
    } finally {
      setUploading(false);
    }
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    const form = new FormData(event.currentTarget);
    const price = String(form.get('price')).replace(',', '.');
    if (!/^\d+(\.\d{1,2})?$/.test(price)) {
      setError('Saisissez un prix positif avec deux décimales maximum.');
      return;
    }
    const body = {
      version: dish?.version,
      name: String(form.get('name')),
      description: String(form.get('description')),
      priceCents: Math.round(Number(price) * 100),
      categoryId: form.get('categoryId') || null,
      allergens: String(form.get('allergens'))
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean),
      imageId,
      isAvailable: form.get('isAvailable') === 'on',
      sortOrder: Number(form.get('sortOrder')),
      modelGlbUrl: form.get('modelGlbUrl') || null,
      modelUsdzUrl: form.get('modelUsdzUrl') || null,
    };
    setBusy(true);
    try {
      await api(dish ? `/api/dishes/${dish.id}` : '/api/dishes', {
        method: dish ? 'PATCH' : 'POST',
        body: JSON.stringify(body),
      });
      await onSaved();
      onClose();
    } catch (err) {
      setError(
        err instanceof ApiClientError && err.status === 409
          ? 'Ce plat a été modifié ailleurs. Vos saisies sont conservées ici. Fermez puis rouvrez la fiche pour charger la dernière version avant de les reporter.'
          : err instanceof Error
            ? err.message
            : 'Enregistrement impossible.',
      );
    } finally {
      setBusy(false);
    }
  }
  async function remove() {
    if (!dish) return;
    setBusy(true);
    setError('');
    try {
      await api(`/api/dishes/${dish.id}`, {
        method: 'DELETE',
        body: JSON.stringify({ version: dish.version }),
      });
      await onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Suppression impossible.');
      setBusy(false);
    }
  }
  return (
    <dialog
      ref={modal}
      className="editor-dialog"
      onCancel={(event) => {
        if (busy || uploading) event.preventDefault();
        else onClose();
      }}
    >
      <header className="dialog-header">
        <div>
          <p className="eyebrow">VOTRE CATALOGUE</p>
          <h2>{dish ? 'Modifier le plat' : 'Un nouveau plat'}</h2>
        </div>
        <button
          className="icon-button"
          onClick={onClose}
          disabled={busy || uploading}
          aria-label="Fermer la fiche"
        >
          <X size={21} />
        </button>
      </header>
      <form onSubmit={submit}>
        <div className="editor-body form-stack">
          <div className="photo-upload">
            <div>
              {imageId ? (
                <img src={dishImageUrl({ imageId })!} alt="Photo du plat" />
              ) : (
                <ImageIcon size={30} />
              )}
            </div>
            <div>
              <strong>La photo qui donne envie</strong>
              <p>JPEG, PNG ou WebP · 3 Mo maximum</p>
              <input
                ref={photoInput}
                className="visually-hidden"
                type="file"
                accept="image/jpeg,image/png,image/webp"
                aria-label="Choisir la photo du plat"
                onChange={(event) => {
                  void upload(event.target.files?.[0]);
                  event.target.value = '';
                }}
              />
              <button
                className="button button-secondary button-small"
                type="button"
                disabled={uploading || busy}
                onClick={() => photoInput.current?.click()}
              >
                {uploading ? (
                  <>
                    <LoaderCircle size={15} className="spin" /> Import…
                  </>
                ) : (
                  <>
                    <Upload size={15} /> {imageId ? 'Remplacer' : 'Importer une photo'}
                  </>
                )}
              </button>
              {imageId && (
                <button
                  className="text-button small"
                  type="button"
                  disabled={uploading || busy}
                  onClick={() => setImageId(null)}
                >
                  Retirer la photo
                </button>
              )}
            </div>
          </div>
          <label>
            Nom du plat
            <input
              name="name"
              defaultValue={source.name}
              required
              maxLength={120}
              placeholder="Le plat signature"
            />
          </label>
          <label>
            Description
            <textarea
              name="description"
              defaultValue={source.description}
              rows={3}
              maxLength={1000}
              placeholder="Les ingrédients, la touche du chef…"
            />
          </label>
          <div className="form-two">
            <label>
              Prix
              <input
                name="price"
                inputMode="decimal"
                required
                defaultValue={(source.priceCents / 100).toFixed(2).replace('.', ',')}
                placeholder="18,50"
              />
            </label>
            <label>
              Catégorie
              <select name="categoryId" defaultValue={source.categoryId || ''}>
                <option value="">Sans catégorie</option>
                {categories.map((category) => (
                  <option value={category.id} key={category.id}>
                    {category.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label>
            Allergènes déclarés
            <input
              name="allergens"
              defaultValue={source.allergens.join(', ')}
              placeholder="Gluten, lait, œufs…"
              maxLength={500}
            />
            <span className="field-hint">
              Séparez les allergènes par une virgule. Vérifiez la recette avant publication.
            </span>
          </label>
          <div className="form-two">
            <label>
              Position dans la carte
              <input
                name="sortOrder"
                type="number"
                min="0"
                max="9999"
                defaultValue={source.sortOrder}
              />
            </label>
            <label className="checkbox-label">
              <input type="checkbox" name="isAvailable" defaultChecked={source.isAvailable} />{' '}
              Disponible à la carte
            </label>
          </div>
          <details className="model-fields">
            <summary>
              Ajouter des modèles 3D déjà validés <ChevronRight size={16} />
            </summary>
            <p className="field-hint">
              Les URLs HTTPS doivent pointer vers vos fichiers publics GLB et USDZ. Vérifiez la
              portion et l’échelle sur téléphone avant de publier.
            </p>
            <label>
              Fichier GLB
              <input
                name="modelGlbUrl"
                type="url"
                defaultValue={source.modelGlbUrl || ''}
                placeholder="https://vos-medias.fr/plat.glb"
              />
            </label>
            <label>
              Fichier USDZ pour iPhone
              <input
                name="modelUsdzUrl"
                type="url"
                defaultValue={source.modelUsdzUrl || ''}
                placeholder="https://vos-medias.fr/plat.usdz"
              />
            </label>
            {dish && (
              <Link className="inline-link" href={`/capture?dish=${encodeURIComponent(dish.id)}`}>
                Préparer de nouvelles photos <Camera size={16} />
              </Link>
            )}
          </details>
          {error && (
            <p role="alert" className="notice notice-error">
              {error}
            </p>
          )}
          {deletePrompt && (
            <div className="notice notice-error">
              <p>
                Supprimer « {dish?.name} » du brouillon ? La carte publiée reste intacte jusqu’à la
                prochaine publication.
              </p>
              <div className="button-row">
                <button
                  type="button"
                  className="button button-danger button-small"
                  onClick={remove}
                  disabled={busy}
                >
                  Confirmer la suppression
                </button>
                <button
                  type="button"
                  className="text-button"
                  onClick={() => setDeletePrompt(false)}
                >
                  Annuler
                </button>
              </div>
            </div>
          )}
        </div>
        <footer className="editor-footer">
          {dish ? (
            <button
              className="icon-button danger"
              type="button"
              aria-label="Supprimer le plat"
              onClick={() => setDeletePrompt(true)}
              disabled={busy}
            >
              <Trash2 size={19} />
            </button>
          ) : (
            <span className="field-hint">Enregistré comme brouillon</span>
          )}
          <button className="button button-blue" disabled={busy || uploading}>
            {busy ? (
              <>
                <LoaderCircle size={17} className="spin" /> Enregistrement…
              </>
            ) : (
              <>
                <Save size={17} /> Enregistrer le plat
              </>
            )}
          </button>
        </footer>
      </form>
    </dialog>
  );
}

function QRPanel({ workspace }: { workspace: RestaurantWorkspace }) {
  const [svg, setSvg] = useState('');
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');
  useEffect(() => {
    const target = `${window.location.origin}/menu/${workspace.restaurant.slug}`;
    setUrl(target);
    import('qrcode')
      .then((qr) =>
        qr.toString(target, {
          type: 'svg',
          margin: 4,
          width: 512,
          color: { dark: '#20221fff', light: '#ffffffff' },
        }),
      )
      .then(setSvg)
      .catch(() => setError('Le QR n’a pas pu être généré. Rechargez la page.'));
  }, [workspace.restaurant.slug]);
  function download() {
    const objectUrl = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }));
    const link = document.createElement('a');
    link.href = objectUrl;
    link.download = `dishplay-${workspace.restaurant.slug}.svg`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  }
  return (
    <div className="qr-layout">
      <section className="qr-print-card">
        <p className="eyebrow">BIENVENUE À NOTRE TABLE</p>
        <h2>{workspace.restaurant.name}</h2>
        <p>Scannez. Découvrez. Savourez.</p>
        {svg ? (
          <div className="qr-code" dangerouslySetInnerHTML={{ __html: svg }} />
        ) : (
          <div className="qr-code">
            <LoaderCircle className="spin" />
          </div>
        )}
        <span className="qr-url">{url}</span>
        <Brand />
      </section>
      <section className="qr-instructions">
        <p className="eyebrow">UN LIEN QUI DURE</p>
        <h2>
          La carte change.
          <br />
          Votre QR reste.
        </h2>
        <p>
          Ce QR ouvre toujours la dernière version publiée. Vous pouvez mettre à jour les prix et
          les plats sans réimprimer vos supports.
        </p>
        {!workspace.publishedAt && (
          <p className="notice">Publiez votre menu avant de distribuer ce QR.</p>
        )}
        {error && (
          <p className="notice notice-error" role="alert">
            {error}
          </p>
        )}
        <div className="form-stack">
          <button className="button button-blue" onClick={download} disabled={!svg}>
            <Download size={18} /> Télécharger le QR en SVG
          </button>
          <button
            className="button button-secondary"
            onClick={() => window.print()}
            disabled={!svg}
          >
            <Printer size={18} /> Imprimer / enregistrer en PDF
          </button>
          <Link className="inline-link" href={`/menu/${workspace.restaurant.slug}`} target="_blank">
            Ouvrir le lien public <ExternalLink size={16} />
          </Link>
        </div>
        <p className="field-hint">
          Gardez la marge blanche autour du code. Vérifiez le QR imprimé avec votre téléphone avant
          de le placer en salle.
        </p>
      </section>
    </div>
  );
}

export function Dashboard() {
  const router = useRouter();
  const [workspace, setWorkspace] = useState<RestaurantWorkspace | null>(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [tab, setTab] = useState<'catalogue' | 'settings' | 'qr'>('catalogue');
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('all');
  const [editing, setEditing] = useState<Dish | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const preview = useRef<HTMLDialogElement>(null);
  const load = useCallback(async () => {
    try {
      const result = await api<RestaurantWorkspace>('/api/restaurant');
      setWorkspace(result);
      setError('');
    } catch (err) {
      if (err instanceof ApiClientError && err.status === 401) router.replace('/login');
      else setError(err instanceof Error ? err.message : 'Impossible de charger votre espace.');
    }
  }, [router]);
  useEffect(() => {
    void load();
  }, [load]);
  async function mutate(path: string, method: string, body: unknown, success: string) {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      await api(path, { method, body: JSON.stringify(body) });
      await load();
      setMessage(success);
      return true;
    } catch (err) {
      setError(
        err instanceof ApiClientError && err.status === 409
          ? 'Votre carte a changé dans une autre fenêtre. Rechargez les données puis vérifiez vos modifications.'
          : err instanceof Error
            ? err.message
            : 'La demande a échoué.',
      );
      return false;
    } finally {
      setBusy(false);
    }
  }
  async function saveSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!workspace) return;
    const form = new FormData(event.currentTarget);
    await mutate(
      '/api/restaurant',
      'PATCH',
      {
        version: workspace.restaurant.version,
        name: form.get('name'),
        tagline: form.get('tagline'),
        currency: form.get('currency'),
      },
      'Les informations du restaurant sont enregistrées dans le brouillon.',
    );
  }
  const dishes =
    workspace?.dishes
      .filter(
        (dish) =>
          `${dish.name} ${dish.description}`
            .toLocaleLowerCase('fr')
            .includes(search.toLocaleLowerCase('fr')) &&
          (filter === 'all' || (filter === 'available' ? dish.isAvailable : !dish.isAvailable)),
      )
      .toSorted((a, b) => a.sortOrder - b.sortOrder) || [];
  return (
    <div className="dashboard-layout">
      <aside className="dashboard-sidebar">
        <Brand />
        <div className="restaurant-chip">
          <span>{workspace?.restaurant.name.slice(0, 1) || 'R'}</span>
          <div>
            <strong>{workspace?.restaurant.name || 'Mon restaurant'}</strong>
            <small>Espace restaurant</small>
          </div>
        </div>
        <nav aria-label="Espace restaurant">
          <button
            aria-current={tab === 'catalogue' ? 'page' : undefined}
            onClick={() => setTab('catalogue')}
          >
            <LayoutGrid size={18} /> Ma carte <span>{workspace?.dishes.length || 0}</span>
          </button>
          <Link href="/capture">
            <Camera size={18} /> Capture photo <ArrowUpRight size={14} />
          </Link>
          <button aria-current={tab === 'qr' ? 'page' : undefined} onClick={() => setTab('qr')}>
            <QrCode size={18} /> QR & partage
          </button>
          <button
            aria-current={tab === 'settings' ? 'page' : undefined}
            onClick={() => setTab('settings')}
          >
            <Settings2 size={18} /> Mon restaurant
          </button>
        </nav>
        <div className="sidebar-bottom">
          <p>
            Une carte à votre image.
            <br />
            Un lien à partager.
          </p>
          <button
            className="text-button"
            onClick={async () => {
              try {
                await api('/api/auth/logout', { method: 'POST' });
                router.replace('/login');
              } catch {
                setError('La déconnexion a échoué. Réessayez.');
              }
            }}
          >
            <LogOut size={16} /> Se déconnecter
          </button>
        </div>
      </aside>
      <div className="dashboard-content">
        <header className="dashboard-topbar">
          <span>
            Espace restaurant <ChevronRight size={14} />{' '}
            <strong>
              {tab === 'catalogue' ? 'Ma carte' : tab === 'qr' ? 'QR & partage' : 'Mon restaurant'}
            </strong>
          </span>
          <Link href="/menu/demo" className="subtle-link">
            Besoin d’inspiration ? <ArrowUpRight size={15} />
          </Link>
          <button
            className="icon-button mobile-logout"
            aria-label="Fermer la session"
            onClick={async () => {
              try {
                await api('/api/auth/logout', { method: 'POST' });
                router.replace('/login');
              } catch {
                setError('La déconnexion a échoué. Réessayez.');
              }
            }}
          >
            <LogOut size={17} />
          </button>
        </header>
        <main id="main" className="dashboard-main">
          {error && (
            <div className="notice notice-error" role="alert">
              <p>{error}</p>
              <button className="text-button" onClick={() => void load()}>
                Recharger les données
              </button>
            </div>
          )}
          {message && (
            <div className="notice notice-success" role="status">
              <CheckCircle2 size={17} />
              {message}
              <button
                className="icon-button"
                aria-label="Fermer le message"
                onClick={() => setMessage('')}
              >
                <X size={16} />
              </button>
            </div>
          )}
          {!workspace ? (
            <div className="empty-state">
              <LoaderCircle className="spin" size={28} />
              <p>Ouverture de votre espace…</p>
            </div>
          ) : (
            <>
              <div className="dashboard-title">
                <div>
                  <p className="eyebrow">
                    {tab === 'catalogue'
                      ? 'L’ATELIER DE VOTRE MENU'
                      : tab === 'qr'
                        ? 'À PARTAGER, SANS MODÉRATION'
                        : 'VOTRE IDENTITÉ'}
                  </p>
                  <h1>
                    {tab === 'catalogue'
                      ? 'À la carte.'
                      : tab === 'qr'
                        ? 'De l’écran à la table.'
                        : 'Votre restaurant.'}
                  </h1>
                  <p>
                    {tab === 'catalogue'
                      ? 'De belles assiettes. Des informations à jour. Tout est ici.'
                      : tab === 'qr'
                        ? 'Un QR permanent pour faire découvrir votre menu.'
                        : 'Les détails qui accueillent vos clients.'}
                  </p>
                </div>
                {tab === 'catalogue' && (
                  <button className="button button-blue" onClick={() => setEditing(null)}>
                    <Plus size={18} /> Ajouter un plat
                  </button>
                )}
              </div>
              {tab === 'catalogue' && (
                <>
                  <div className="publication-bar">
                    <div>
                      <span className={`status-dot ${workspace.publishedAt ? 'green' : ''}`} />
                      <div>
                        <strong>
                          {workspace.publishedAt
                            ? 'Une version de votre carte est en ligne'
                            : 'Votre carte est en brouillon'}
                        </strong>
                        <span>
                          {workspace.publishedAt
                            ? `Dernière publication : ${new Date(workspace.publishedAt).toLocaleString('fr-FR')}`
                            : 'Prévisualisez votre menu, puis publiez-le pour vos clients.'}
                        </span>
                      </div>
                    </div>
                    <div className="button-row">
                      <button
                        className="button button-secondary button-small"
                        onClick={() => preview.current?.showModal()}
                      >
                        <Eye size={16} /> Prévisualiser
                      </button>
                      <button
                        className="button button-dark button-small"
                        disabled={busy || !workspace.dishes.length}
                        onClick={() =>
                          void mutate(
                            '/api/publish',
                            'POST',
                            { version: workspace.restaurant.version },
                            'Votre carte est publiée. Le QR conserve la même adresse.',
                          )
                        }
                      >
                        <Check size={16} />
                        {busy ? 'Publication…' : 'Publier la carte'}
                      </button>
                    </div>
                  </div>
                  <div className="catalogue-toolbar">
                    <div className="search-input">
                      <Search size={18} />
                      <input
                        aria-label="Rechercher un plat"
                        placeholder="Rechercher un plat…"
                        value={search}
                        onChange={(event) => setSearch(event.target.value)}
                      />
                    </div>
                    <select
                      value={filter}
                      aria-label="Filtrer la disponibilité"
                      onChange={(event) => setFilter(event.target.value)}
                    >
                      <option value="all">Tous les plats</option>
                      <option value="available">Disponibles</option>
                      <option value="unavailable">Indisponibles</option>
                    </select>
                    <span>
                      {dishes.length} plat{dishes.length !== 1 ? 's' : ''}
                    </span>
                  </div>
                  {dishes.length ? (
                    <div className="catalogue-list">
                      <div className="catalogue-labels">
                        <span>LE PLAT</span>
                        <span>CATÉGORIE</span>
                        <span>PRIX</span>
                        <span>DISPONIBILITÉ</span>
                        <span />
                      </div>
                      {dishes.map((dish) => (
                        <article className="catalogue-row" key={dish.id}>
                          <div className="catalogue-dish">
                            {dishImageUrl(dish) ? (
                              <img src={dishImageUrl(dish)!} alt="" width="72" height="72" />
                            ) : (
                              <div className="catalogue-placeholder">
                                <ImageIcon size={23} />
                              </div>
                            )}
                            <div>
                              <button className="dish-name-button" onClick={() => setEditing(dish)}>
                                {dish.name}
                              </button>
                              <span>{dish.modelGlbUrl ? 'Photo & modèle 3D' : 'Carte photo'}</span>
                            </div>
                          </div>
                          <span className="catalogue-category">
                            {workspace.categories.find((item) => item.id === dish.categoryId)
                              ?.name || 'Sans catégorie'}
                          </span>
                          <strong className="catalogue-price">
                            {formatPrice(dish.priceCents, workspace.restaurant.currency)}
                          </strong>
                          <button
                            className={`availability ${dish.isAvailable ? 'available' : ''}`}
                            disabled={busy}
                            aria-label={`${dish.name} : ${dish.isAvailable ? 'disponible, rendre indisponible' : 'indisponible, rendre disponible'}`}
                            onClick={() =>
                              void mutate(
                                `/api/dishes/${dish.id}`,
                                'PATCH',
                                { version: dish.version, isAvailable: !dish.isAvailable },
                                'Disponibilité enregistrée. Publiez pour actualiser le menu client.',
                              )
                            }
                          >
                            <span />
                            {dish.isAvailable ? 'Disponible' : 'Indisponible'}
                          </button>
                          <button
                            className="icon-button"
                            aria-label={`Modifier ${dish.name}`}
                            onClick={() => setEditing(dish)}
                          >
                            <MoreHorizontal size={21} />
                          </button>
                        </article>
                      ))}
                    </div>
                  ) : (
                    <div className="empty-state catalogue-empty">
                      <div className="empty-icon">
                        <ImageIcon size={30} />
                      </div>
                      <h2>
                        {search || filter !== 'all'
                          ? 'Aucun plat ne correspond.'
                          : 'Votre premier plat ouvre le bal.'}
                      </h2>
                      <p>
                        {search || filter !== 'all'
                          ? 'Essayez un autre nom ou filtre.'
                          : 'Ajoutez une photo, quelques mots et un prix. Votre carte prend vie.'}
                      </p>
                      {!search && filter === 'all' && (
                        <button className="button button-blue" onClick={() => setEditing(null)}>
                          <Plus size={17} /> Ajouter mon premier plat
                        </button>
                      )}
                    </div>
                  )}
                  <div className="dashboard-help">
                    <Camera size={22} />
                    <div>
                      <strong>Une nouvelle perspective sur vos plats.</strong>
                      <p>Préparez vos prises avec la capture photo guidée.</p>
                    </div>
                    <Link href="/capture" className="inline-link">
                      Ouvrir la capture <ArrowUpRight size={17} />
                    </Link>
                  </div>
                </>
              )}
              {tab === 'qr' && <QRPanel workspace={workspace} />}
              {tab === 'settings' && (
                <div className="settings-grid">
                  <section className="settings-card">
                    <h2>Les informations de la carte</h2>
                    <form
                      onSubmit={saveSettings}
                      className="form-stack"
                      key={workspace.restaurant.id}
                    >
                      <label>
                        Nom du restaurant
                        <input
                          name="name"
                          required
                          defaultValue={workspace.restaurant.name}
                          maxLength={100}
                        />
                      </label>
                      <label>
                        Quelques mots pour accueillir vos clients
                        <textarea
                          name="tagline"
                          defaultValue={workspace.restaurant.tagline}
                          maxLength={240}
                          rows={3}
                        />
                      </label>
                      <label>
                        Devise
                        <select name="currency" defaultValue={workspace.restaurant.currency}>
                          <option value="EUR">Euro — EUR</option>
                          <option value="USD">Dollar américain — USD</option>
                          <option value="CAD">Dollar canadien — CAD</option>
                        </select>
                        <span className="field-hint">
                          La devise change le symbole affiché, sans convertir les montants.
                        </span>
                      </label>
                      <button className="button button-blue" disabled={busy}>
                        <Save size={17} /> Enregistrer
                      </button>
                    </form>
                  </section>
                  <section className="settings-card">
                    <h2>Les catégories</h2>
                    <p>Organisez votre carte par moments et par envies.</p>
                    <div className="category-management">
                      {workspace.categories
                        .toSorted((a, b) => a.sortOrder - b.sortOrder)
                        .map((category) => (
                          <CategoryRow
                            key={category.id}
                            category={category}
                            busy={busy}
                            mutate={mutate}
                          />
                        ))}
                    </div>
                    <form
                      className="category-add"
                      onSubmit={async (event) => {
                        event.preventDefault();
                        const form = event.currentTarget;
                        const name = new FormData(form).get('name');
                        if (await mutate('/api/categories', 'POST', { name }, 'Catégorie ajoutée.'))
                          form.reset();
                      }}
                    >
                      <label className="visually-hidden" htmlFor="category-name">
                        Nouvelle catégorie
                      </label>
                      <input
                        id="category-name"
                        name="name"
                        placeholder="Nouvelle catégorie"
                        required
                        maxLength={80}
                      />
                      <button
                        className="icon-button"
                        aria-label="Ajouter la catégorie"
                        disabled={busy}
                      >
                        <Plus size={20} />
                      </button>
                    </form>
                  </section>
                </div>
              )}
              <dialog className="preview-dialog" ref={preview}>
                <div className="preview-dialog-bar">
                  <span>Aperçu du brouillon · Vue client</span>
                  <button
                    className="button button-secondary button-small"
                    onClick={() => preview.current?.close()}
                  >
                    <X size={16} /> Fermer l’aperçu
                  </button>
                </div>
                <MenuView menu={workspace} preview />
              </dialog>
              {editing !== undefined && (
                <DishEditor
                  dish={editing}
                  categories={workspace.categories}
                  onClose={() => setEditing(undefined)}
                  onSaved={async () => {
                    await load();
                    setMessage(
                      'Plat enregistré. Publiez votre carte pour rendre la modification visible.',
                    );
                  }}
                />
              )}
            </>
          )}
        </main>
      </div>
    </div>
  );
}

function CategoryRow({
  category,
  busy,
  mutate,
}: {
  category: Category;
  busy: boolean;
  mutate: (path: string, method: string, body: unknown, success: string) => Promise<boolean>;
}) {
  const [confirm, setConfirm] = useState(false);
  return (
    <div className="category-management-row">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          void mutate(
            `/api/categories/${category.id}`,
            'PATCH',
            { name: form.get('name'), sortOrder: Number(form.get('sortOrder')) },
            'Catégorie enregistrée.',
          );
        }}
      >
        <input
          name="name"
          aria-label={`Nom de la catégorie ${category.name}`}
          defaultValue={category.name}
          required
          maxLength={80}
        />
        <input
          name="sortOrder"
          className="order-input"
          aria-label={`Position de ${category.name}`}
          type="number"
          min="0"
          max="9999"
          defaultValue={category.sortOrder}
        />
        <button className="icon-button" aria-label={`Enregistrer ${category.name}`} disabled={busy}>
          <Check size={17} />
        </button>
      </form>
      <button
        className="icon-button danger"
        aria-label={`Supprimer ${category.name}`}
        disabled={busy}
        onClick={() => setConfirm(!confirm)}
      >
        <Trash2 size={16} />
      </button>
      {confirm && (
        <div className="category-delete-confirm">
          <p>Supprimer cette catégorie ? Les plats seront conservés sans catégorie.</p>
          <button
            className="button button-danger button-small"
            disabled={busy}
            onClick={() =>
              void mutate(`/api/categories/${category.id}`, 'DELETE', {}, 'Catégorie supprimée.')
            }
          >
            Supprimer
          </button>
        </div>
      )}
    </div>
  );
}
