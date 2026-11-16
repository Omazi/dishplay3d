-- DishPlay — object storage, 3D models, QR codes, restaurant look. Additive: applies on top of the
-- website's migrations 001-005 (branch main1) and can be re-run safely.
--
-- Rule of the model: every row belongs to exactly one restaurant, and a row can only point at rows and
-- files of the SAME restaurant (composite foreign keys below). File bytes never live in the database:
-- the database stores where each file is in object storage (S3 or compatible).

-- Lets other tables say "this dish / object / scan of this restaurant" in one foreign key.
CREATE UNIQUE INDEX IF NOT EXISTS dishes_id_restaurant ON dishes(id, restaurant_id);
CREATE UNIQUE INDEX IF NOT EXISTS categories_id_restaurant ON categories(id, restaurant_id);
CREATE UNIQUE INDEX IF NOT EXISTS scan_sessions_id_restaurant ON scan_sessions(id, restaurant_id);

-- ---------------------------------------------------------------------------------------------------
-- Files in object storage. Key layout (see db/README.md):  r/{restaurant_id}/...
CREATE TABLE IF NOT EXISTS storage_objects (
  id text PRIMARY KEY,
  restaurant_id text NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
  bucket text NOT NULL,
  object_key text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('dish_image','logo','cover','model_glb','model_usdz','model_splat',
                                     'model_poster','model_video','scan_frame','scan_archive','qr_image')),
  mime_type text NOT NULL,
  byte_size bigint NOT NULL CHECK (byte_size > 0),
  sha256 text NOT NULL CHECK (sha256 ~ '^[a-f0-9]{64}$'),
  visibility text NOT NULL DEFAULT 'private' CHECK (visibility IN ('private','public')),
  state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','ready','deleted')),
  created_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  UNIQUE (bucket, object_key),
  UNIQUE (id, restaurant_id),
  -- A restaurant's files live under its own prefix: one restaurant can never be handed another's key.
  CONSTRAINT storage_objects_tenant_prefix CHECK (starts_with(object_key, 'r/' || restaurant_id || '/'))
);
CREATE INDEX IF NOT EXISTS storage_objects_by_kind ON storage_objects(restaurant_id, kind) WHERE state <> 'deleted';

-- Photos of the menu used to be stored inside the database (base64). New ones go to object storage.
ALTER TABLE media_assets ALTER COLUMN content_base64 DROP NOT NULL;
ALTER TABLE media_assets ADD COLUMN IF NOT EXISTS storage_object_id text;
ALTER TABLE media_assets DROP CONSTRAINT IF EXISTS media_assets_storage_fk;
ALTER TABLE media_assets ADD CONSTRAINT media_assets_storage_fk
  FOREIGN KEY (storage_object_id, restaurant_id) REFERENCES storage_objects(id, restaurant_id);
ALTER TABLE media_assets DROP CONSTRAINT IF EXISTS media_assets_has_content;
ALTER TABLE media_assets ADD CONSTRAINT media_assets_has_content
  CHECK (content_base64 IS NOT NULL OR storage_object_id IS NOT NULL);

-- ---------------------------------------------------------------------------------------------------
-- One 3D result of one scan of one dish. A dish keeps its history; at most one model is published.
CREATE TABLE IF NOT EXISTS dish_models (
  id text PRIMARY KEY,
  restaurant_id text NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
  dish_id text NOT NULL,
  scan_id text,
  revision integer NOT NULL CHECK (revision > 0),
  method text NOT NULL CHECK (method IN ('stereo_mesh','gaussian_splat','imported')),
  engine text NOT NULL,                       -- e.g. p1-0.2.0, gsplat-1.5.3
  state text NOT NULL DEFAULT 'processing'
    CHECK (state IN ('processing','ready_for_review','published','rejected','failed')),
  glb_object_id text,                         -- mesh for the web viewer and Android
  usdz_object_id text,                        -- mesh for AR Quick Look on iPhone
  splat_object_id text,                       -- Gaussian splat (photoreal view)
  poster_object_id text,                      -- still picture shown before the 3D loads
  video_object_id text,                       -- turntable video (fallback where 3D is too heavy)
  width_m double precision CHECK (width_m > 0),
  height_m double precision CHECK (height_m > 0),
  depth_m double precision CHECK (depth_m > 0),
  metrics jsonb NOT NULL DEFAULT '{}',        -- held-out PSNR, triangles, gaussians, measured share...
  created_at timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz,
  UNIQUE (dish_id, revision),
  FOREIGN KEY (dish_id, restaurant_id) REFERENCES dishes(id, restaurant_id) ON DELETE CASCADE,
  FOREIGN KEY (scan_id, restaurant_id) REFERENCES scan_sessions(id, restaurant_id),
  FOREIGN KEY (glb_object_id, restaurant_id) REFERENCES storage_objects(id, restaurant_id),
  FOREIGN KEY (usdz_object_id, restaurant_id) REFERENCES storage_objects(id, restaurant_id),
  FOREIGN KEY (splat_object_id, restaurant_id) REFERENCES storage_objects(id, restaurant_id),
  FOREIGN KEY (poster_object_id, restaurant_id) REFERENCES storage_objects(id, restaurant_id),
  FOREIGN KEY (video_object_id, restaurant_id) REFERENCES storage_objects(id, restaurant_id),
  -- Nothing can be shown to diners without at least one viewable file.
  CONSTRAINT dish_models_published_has_file CHECK (
    state <> 'published' OR glb_object_id IS NOT NULL OR splat_object_id IS NOT NULL OR video_object_id IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS dish_models_one_published ON dish_models(dish_id) WHERE state = 'published';
CREATE INDEX IF NOT EXISTS dish_models_by_restaurant ON dish_models(restaurant_id, created_at DESC);

-- Where a scan came from and where its raw views are kept.
ALTER TABLE scan_sessions ADD COLUMN IF NOT EXISTS calculator_session_id text;
ALTER TABLE scan_sessions ADD COLUMN IF NOT EXISTS device jsonb NOT NULL DEFAULT '{}';
ALTER TABLE scan_sessions ADD COLUMN IF NOT EXISTS box jsonb;
ALTER TABLE scan_sessions ADD COLUMN IF NOT EXISTS frames_prefix text;
ALTER TABLE scan_sessions ADD COLUMN IF NOT EXISTS frame_count integer CHECK (frame_count >= 0);

-- ---------------------------------------------------------------------------------------------------
-- QR codes: as many as the restaurant wants (one per table, terrace, window...). The printed URL is
-- /q/{code}; it keeps working when the menu, the slug or the dish changes.
CREATE TABLE IF NOT EXISTS qr_codes (
  id text PRIMARY KEY,
  restaurant_id text NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
  code text NOT NULL UNIQUE CHECK (code ~ '^[a-z0-9-]{3,64}$'),
  label text NOT NULL DEFAULT '',
  target text NOT NULL DEFAULT 'menu' CHECK (target IN ('menu','category','dish')),
  category_id text,
  dish_id text,
  image_object_id text,
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  revoked_at timestamptz,
  UNIQUE (id, restaurant_id),
  FOREIGN KEY (category_id, restaurant_id) REFERENCES categories(id, restaurant_id),
  FOREIGN KEY (dish_id, restaurant_id) REFERENCES dishes(id, restaurant_id),
  FOREIGN KEY (image_object_id, restaurant_id) REFERENCES storage_objects(id, restaurant_id),
  CONSTRAINT qr_codes_target_matches CHECK (
    (target = 'menu' AND category_id IS NULL AND dish_id IS NULL)
    OR (target = 'category' AND category_id IS NOT NULL AND dish_id IS NULL)
    OR (target = 'dish' AND dish_id IS NOT NULL AND category_id IS NULL))
);
CREATE INDEX IF NOT EXISTS qr_codes_by_restaurant ON qr_codes(restaurant_id) WHERE is_active;
-- The single QR link each restaurant already has becomes its first QR code.
INSERT INTO qr_codes (id, restaurant_id, code, label)
SELECT 'qr_' || q.restaurant_id, q.restaurant_id, q.slug, 'Menu'
FROM qr_links q WHERE q.slug ~ '^[a-z0-9-]{3,64}$'
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------------------------------
-- Each restaurant's own look, and its own web address when it has one.
CREATE TABLE IF NOT EXISTS restaurant_themes (
  restaurant_id text PRIMARY KEY REFERENCES restaurants(id) ON DELETE CASCADE,
  appearance text NOT NULL DEFAULT 'auto' CHECK (appearance IN ('light','dark','auto')),
  accent_color text NOT NULL DEFAULT '#ff943a' CHECK (accent_color ~ '^#[0-9a-fA-F]{6}$'),
  background_color text CHECK (background_color ~ '^#[0-9a-fA-F]{6}$'),
  text_color text CHECK (text_color ~ '^#[0-9a-fA-F]{6}$'),
  font_family text NOT NULL DEFAULT 'system',
  logo_object_id text,
  cover_object_id text,
  layout jsonb NOT NULL DEFAULT '{}',
  updated_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (logo_object_id, restaurant_id) REFERENCES storage_objects(id, restaurant_id),
  FOREIGN KEY (cover_object_id, restaurant_id) REFERENCES storage_objects(id, restaurant_id)
);
CREATE TABLE IF NOT EXISTS restaurant_domains (
  hostname text PRIMARY KEY CHECK (hostname = lower(hostname) AND hostname ~ '^[a-z0-9.-]{4,253}$'),
  restaurant_id text NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
  verified_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS restaurant_domains_by_restaurant ON restaurant_domains(restaurant_id);

-- Menu text in other languages (the base text stays in dishes / categories).
CREATE TABLE IF NOT EXISTS dish_translations (
  dish_id text NOT NULL REFERENCES dishes(id) ON DELETE CASCADE,
  locale text NOT NULL CHECK (locale ~ '^[a-z]{2}(-[A-Z]{2})?$'),
  name text NOT NULL,
  description text NOT NULL DEFAULT '',
  PRIMARY KEY (dish_id, locale)
);
CREATE TABLE IF NOT EXISTS category_translations (
  category_id text NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
  locale text NOT NULL CHECK (locale ~ '^[a-z]{2}(-[A-Z]{2})?$'),
  name text NOT NULL,
  PRIMARY KEY (category_id, locale)
);

-- ---------------------------------------------------------------------------------------------------
-- What diners look at. No IP address, no account: an anonymous visit id that changes every day.
CREATE TABLE IF NOT EXISTS menu_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  restaurant_id text NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
  qr_code_id text,
  dish_id text,
  event text NOT NULL CHECK (event IN ('menu_view','dish_view','model_open','ar_open')),
  visit_hash text,
  locale text,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (qr_code_id, restaurant_id) REFERENCES qr_codes(id, restaurant_id) ON DELETE SET NULL (qr_code_id),
  FOREIGN KEY (dish_id, restaurant_id) REFERENCES dishes(id, restaurant_id) ON DELETE SET NULL (dish_id)
);
CREATE INDEX IF NOT EXISTS menu_events_by_time ON menu_events(restaurant_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS menu_events_by_dish ON menu_events(restaurant_id, dish_id, occurred_at DESC) WHERE dish_id IS NOT NULL;
