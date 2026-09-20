CREATE TABLE IF NOT EXISTS native_capture_links (
  id text PRIMARY KEY,
  restaurant_id text NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
  dish_id text NOT NULL REFERENCES dishes(id) ON DELETE CASCADE,
  created_by text NOT NULL REFERENCES users(id),
  code_hash text NOT NULL UNIQUE,
  code_expires_at timestamptz NOT NULL,
  token_hash text UNIQUE,
  token_expires_at timestamptz,
  scan_id text UNIQUE REFERENCES scan_sessions(id) ON DELETE CASCADE,
  claimed_at timestamptz,
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS native_capture_links_owner ON native_capture_links(restaurant_id,dish_id);
