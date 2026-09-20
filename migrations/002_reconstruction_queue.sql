-- Additive upgrade for the explicitly enabled, external PostgreSQL worker.
ALTER TABLE reconstruction_jobs DROP CONSTRAINT IF EXISTS reconstruction_jobs_state_check;
ALTER TABLE reconstruction_jobs ADD CONSTRAINT reconstruction_jobs_state_check
  CHECK (state IN ('queued','running','ready_for_review','succeeded','failed','cancelled'));
ALTER TABLE reconstruction_jobs ADD COLUMN IF NOT EXISTS worker_id text;
ALTER TABLE reconstruction_jobs ADD COLUMN IF NOT EXISTS lease_generation integer NOT NULL DEFAULT 0;
ALTER TABLE reconstruction_jobs ADD COLUMN IF NOT EXISTS available_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE reconstruction_jobs ADD COLUMN IF NOT EXISTS stage text;
CREATE INDEX IF NOT EXISTS reconstruction_queue_claim ON reconstruction_jobs(state,available_at,created_at);
CREATE TABLE IF NOT EXISTS reconstruction_workers (
  id text PRIMARY KEY, engine text NOT NULL, capabilities jsonb NOT NULL,
  ready boolean NOT NULL DEFAULT false, started_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS reconstruction_workers_fresh ON reconstruction_workers(engine,last_seen_at);
CREATE TABLE IF NOT EXISTS reconstruction_capacity (
  id integer PRIMARY KEY CHECK(id=1)
);
INSERT INTO reconstruction_capacity(id) VALUES(1) ON CONFLICT DO NOTHING;
ALTER TABLE reconstruction_capacity ADD COLUMN IF NOT EXISTS job_id text;
ALTER TABLE reconstruction_capacity ADD COLUMN IF NOT EXISTS worker_id text;
ALTER TABLE reconstruction_capacity ADD COLUMN IF NOT EXISTS lease_token text;
ALTER TABLE reconstruction_capacity ADD COLUMN IF NOT EXISTS lease_generation integer;
ALTER TABLE reconstruction_capacity ADD COLUMN IF NOT EXISTS blocked_until timestamptz;
-- Preserve an already running legacy lease while upgrading the singleton slot.
UPDATE reconstruction_capacity c SET job_id=j.id,worker_id=j.worker_id,lease_token=j.lease_token,
  lease_generation=j.lease_generation,blocked_until=j.lease_until+interval '5 seconds'
FROM (SELECT * FROM reconstruction_jobs WHERE state='running' AND lease_until>clock_timestamp()
      ORDER BY created_at LIMIT 1) j
WHERE c.id=1 AND c.blocked_until IS NULL;
