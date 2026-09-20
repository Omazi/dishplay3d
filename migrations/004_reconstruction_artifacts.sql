-- Private exports, transferred in bounded pieces to fit serverless response limits.
-- A piece is readable only through its owned, successfully completed job generation.
CREATE TABLE IF NOT EXISTS reconstruction_artifact_parts (
  job_id text NOT NULL REFERENCES reconstruction_jobs(id) ON DELETE CASCADE,
  generation integer NOT NULL,
  kind text NOT NULL CHECK(kind IN ('glb','usdz')),
  part integer NOT NULL CHECK(part >= 0 AND part < 128),
  bytes bytea NOT NULL CHECK(octet_length(bytes) <= 1048576),
  PRIMARY KEY(job_id,generation,kind,part)
);
