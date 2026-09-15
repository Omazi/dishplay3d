CREATE TABLE IF NOT EXISTS users (
  id text PRIMARY KEY, email text NOT NULL UNIQUE, password_hash text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS restaurants (
  id text PRIMARY KEY, name text NOT NULL, slug text NOT NULL UNIQUE,
  tagline text NOT NULL DEFAULT '', currency text NOT NULL DEFAULT 'EUR',
  version integer NOT NULL DEFAULT 1, published_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS memberships (
  user_id text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  restaurant_id text NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
  role text NOT NULL CHECK (role IN ('owner','editor')),
  PRIMARY KEY(user_id,restaurant_id)
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash text PRIMARY KEY, user_id text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at);
CREATE TABLE IF NOT EXISTS categories (
  id text PRIMARY KEY, restaurant_id text NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
  name text NOT NULL, sort_order integer NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS media_assets (
  id text PRIMARY KEY, restaurant_id text NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
  mime_type text NOT NULL, byte_size integer NOT NULL, sha256 text NOT NULL,
  content_base64 text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(restaurant_id,sha256)
);
CREATE TABLE IF NOT EXISTS dishes (
  id text PRIMARY KEY, restaurant_id text NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
  category_id text REFERENCES categories(id) ON DELETE SET NULL,
  name text NOT NULL, description text NOT NULL DEFAULT '', price_cents integer NOT NULL CHECK(price_cents >= 0),
  allergens jsonb NOT NULL DEFAULT '[]', image_id text REFERENCES media_assets(id),
  model_glb_url text, model_usdz_url text, model_source text,
  version integer NOT NULL DEFAULT 1, sort_order integer NOT NULL DEFAULT 0,
  is_available boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS dishes_restaurant ON dishes(restaurant_id);
CREATE TABLE IF NOT EXISTS dish_revisions (
  id text PRIMARY KEY, dish_id text NOT NULL REFERENCES dishes(id) ON DELETE CASCADE,
  restaurant_id text NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
  geometry_revision integer NOT NULL, model_glb_url text, model_usdz_url text,
  source text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS published_menu_versions (
  id text PRIMARY KEY, restaurant_id text NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
  version integer NOT NULL, snapshot jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(restaurant_id,version)
);
CREATE INDEX IF NOT EXISTS published_menu_latest ON published_menu_versions(restaurant_id,version DESC);
CREATE TABLE IF NOT EXISTS published_media (
  restaurant_id text NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
  media_id text NOT NULL REFERENCES media_assets(id), PRIMARY KEY(restaurant_id,media_id)
);
CREATE TABLE IF NOT EXISTS qr_links (
  restaurant_id text PRIMARY KEY REFERENCES restaurants(id) ON DELETE CASCADE,
  slug text NOT NULL UNIQUE, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS audit_events (
  id text PRIMARY KEY, restaurant_id text NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
  actor_id text REFERENCES users(id), action text NOT NULL,
  details jsonb NOT NULL DEFAULT '{}', created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS rate_limits (
  key text PRIMARY KEY, attempts integer NOT NULL, window_start timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS rate_limits_expiry ON rate_limits(window_start);
CREATE TABLE IF NOT EXISTS scan_sessions (
  id text PRIMARY KEY, restaurant_id text NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
  dish_id text NOT NULL REFERENCES dishes(id) ON DELETE CASCADE,
  state text NOT NULL CHECK(state IN ('capturing','finalized','cancelled')) DEFAULT 'capturing',
  manifest_hash text, created_at timestamptz NOT NULL DEFAULT now(), finalized_at timestamptz
);
CREATE TABLE IF NOT EXISTS scan_frames (
  id text PRIMARY KEY, scan_id text NOT NULL REFERENCES scan_sessions(id) ON DELETE CASCADE,
  media_id text NOT NULL REFERENCES media_assets(id), sha256 text NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}', created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(scan_id,sha256)
);
CREATE TABLE IF NOT EXISTS reconstruction_jobs (
  id text PRIMARY KEY, restaurant_id text NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
  scan_id text NOT NULL REFERENCES scan_sessions(id), input_hash text NOT NULL,
  engine text NOT NULL, settings jsonb NOT NULL, state text NOT NULL DEFAULT 'queued'
    CHECK(state IN ('queued','running','succeeded','failed','cancelled')),
  lease_until timestamptz, lease_token text, attempts integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 2, error_code text, result jsonb,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(restaurant_id,input_hash,engine)
);
