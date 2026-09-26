-- Additive: existing scans remain schema 1; never rewrite frozen identities.
ALTER TABLE scan_sessions ADD COLUMN IF NOT EXISTS source_type text NOT NULL DEFAULT 'photos' CHECK (source_type IN ('photos','video'));
ALTER TABLE scan_sessions ADD COLUMN IF NOT EXISTS manifest_schema integer NOT NULL DEFAULT 1 CHECK (manifest_schema IN (1,2));
ALTER TABLE scan_sessions ADD COLUMN IF NOT EXISTS capture_metadata jsonb NOT NULL DEFAULT '{}';
ALTER TABLE scan_frames ADD COLUMN IF NOT EXISTS frame_index integer CHECK (frame_index >= 0);
ALTER TABLE scan_frames ADD COLUMN IF NOT EXISTS timestamp_ms double precision CHECK (timestamp_ms >= 0 AND timestamp_ms < 86400000);
ALTER TABLE scan_frames ADD COLUMN IF NOT EXISTS width integer CHECK (width > 0);
ALTER TABLE scan_frames ADD COLUMN IF NOT EXISTS height integer CHECK (height > 0);
-- Video may contain identical pixels at different times. Keep photo deduplication.
ALTER TABLE scan_frames DROP CONSTRAINT IF EXISTS scan_frames_scan_id_sha256_key;
CREATE UNIQUE INDEX IF NOT EXISTS scan_photo_hash ON scan_frames(scan_id,sha256) WHERE frame_index IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS scan_frame_sequence ON scan_frames(scan_id,frame_index) WHERE frame_index IS NOT NULL;
CREATE TABLE IF NOT EXISTS capture_videos (
  id text PRIMARY KEY,
  scan_id text NOT NULL UNIQUE REFERENCES scan_sessions(id) ON DELETE CASCADE,
  restaurant_id text NOT NULL REFERENCES restaurants(id),
  storage_backend text NOT NULL,
  storage_key text NOT NULL,
  sha256 text NOT NULL CHECK (sha256 ~ '^[a-f0-9]{64}$'),
  byte_size bigint NOT NULL CHECK (byte_size > 0 AND byte_size <= 268435456),
  mime_type text NOT NULL CHECK (mime_type IN ('video/mp4','video/quicktime')),
  created_at timestamptz NOT NULL DEFAULT now()
);
