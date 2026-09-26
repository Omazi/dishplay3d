# Video/order foundation — milestone 1

Scope: extend the existing scans → jobs → supervised Linux worker → Python → COLMAP/OpenMVS/Blender architecture. No frontend or native app changes. Milestones 2–8 are deliberately not implemented in this patch.

## Baseline and audit verification

The pre-change HEAD is recorded in `worker/tests/fixtures/legacy_plan.json`. The fixture was generated from the **pre-change** Python module, then compared with all ten new stage commands. They match exactly, including exhaustive matching, one CPU thread, tool versions and output paths. A regression test now enforces that comparison.

Verified against that HEAD: photo manifest schema 1 hashes sorted SHA-256 values; worker materialization sorted by SHA; there was no raw video input; leases renew during the existing job supervisor; input images live in PostgreSQL; artifacts are private chunked GLB/USDZ. These remain the photo baseline.

`worker/engines.py` registers `legacy-photogrammetry-v1`. The original database engine string and schema-1 job hash remain unchanged. Ordered captures use an additional `:capture2-ffmpeg-temporal1` protocol identity so an old worker cannot accidentally claim them. Both use the same geometry engine. The job result records the friendly engine ID, exact geometry pins, binary checksums, FFmpeg/ffprobe version/build strings and binary checksums.

## File map

Created:

- `migrations/005_ordered_video.sql`: additive columns and raw-video references, partial photo hash uniqueness and unique video frame indexes.
- `src/lib/server/capture-manifest.ts`: schema-1 compatibility, canonical schema-2 identity, metadata parsing and ordered input query.
- `src/lib/server/capture-blob-store.ts`: streaming storage interface and private local disk adapter.
- `src/lib/server/capture-video.ts`: streaming receive and tenant-scoped immutable attachment.
- `src/app/api/scans/[id]/video/route.ts`, `src/app/api/native/video/route.ts`: authenticated raw upload endpoints.
- `worker/video.py`: ISO-BMFF validation, bounded probe/decode, real PTS timestamps, orientation and deterministic extraction.
- `worker/engines.py`: explicit engine registry.
- `tests/capture-manifest.test.ts`, `worker/tests/test_video.py`, `worker/tests/fixtures/legacy_plan.json`: identity, storage, decoder and frozen baseline evidence.
- `scripts/verify-video-api.mjs`: real HTTP checks with a disposable database and storage, without a browser.
- `docs/THIRD_PARTY_3D_LICENSES.md`, this report.

Modified:

- `src/lib/server/scans.ts`, `src/lib/server/jobs.ts`: ordered frames, finalization, admission, compatible workers and manifest validation.
- `src/app/api/scans/route.ts`, both existing native/web `frames/route.ts`: optional capture/frame metadata, without breaking old requests.
- `scripts/worker.ts`: materialization by explicit index, streaming video fetch, source/metadata verification, error forwarding. Existing lease, heartbeat, memory guard, retry and artifact upload machinery remains.
- `worker/reconstruct.py`: video/engine/prepare-only CLI, output metadata, supervised decoding stages; geometry commands unchanged.
- `tests/jobs.test.ts`, `tests/native-capture.test.ts`, `worker/tests/test_reconstruct.py`: database, ordering, queue fencing, lease and baseline regressions.
- `worker/container/Dockerfile`, `scripts/local-worker.sh`: optional FFmpeg dependency and private shared video mount.
- `.github/workflows/ci-cd.yml`: install FFmpeg and isolated pinned Pillow for real decode tests in CI.

## Migration

Migration discovery is already automatic in `database()` and worker startup. `005_ordered_video.sql` is idempotent and leaves existing `manifest_hash` values untouched. Defaults classify old scans as `photos`, schema 1. Do not downgrade to code that assumes `UNIQUE(scan_id,sha256)` for all captures: video frames can legitimately have the same pixels at different times.

New fields: `source_type`, `manifest_schema`, `capture_metadata` on scans; `frame_index`, `timestamp_ms`, `width`, `height` on frames. Existing `metadata` stores camera/lens/intrinsics/pose information when provided. New `capture_videos` stores only storage backend/key, SHA, byte size, MIME, ownership and creation time. No raw video bytes enter PostgreSQL.

## CLI commands

Use a fresh output directory for every run. The default action with `--input` or `--video` is reconstruction; `--plan` launches no engines and writes nothing.

```bash
# Presence check (no reconstruction)
python3 worker/reconstruct.py --doctor

# Decode/validate only, useful on the laptop before installing geometry tools
python3 worker/reconstruct.py --video /absolute/path/scan.mp4 \
  --engine legacy-photogrammetry-v1 --prepare-video \
  --max-images 24 --memory-mib 512 --output .data/video-prepared

# Real video -> existing mesh/AR engine, in the pinned Linux worker environment
python3 worker/reconstruct.py --video /absolute/path/scan.mp4 \
  --engine legacy-photogrammetry-v1 --max-images 24 \
  --memory-mib 1024 --output .data/video-reconstruction

# Existing photos remain supported
python3 worker/reconstruct.py --input /absolute/path/originals \
  --engine legacy-photogrammetry-v1 --output .data/photo-reconstruction

npm run check
npm run build
node scripts/low-memory.mjs node scripts/verify-video-api.mjs
python3 -m unittest discover -s worker/tests
```

The local host has FFmpeg 4.2.7/Pillow 10.4.0 for decoder tests. Actual legacy reconstruction still requires the pinned toolchain/Pillow 12.3.0; the existing Docker image supplies those. The pre-existing Docker image lacks FFmpeg and must be rebuilt to process raw videos. Rebuilding the tools image is intended for GitHub, not for this 8-GB laptop. Existing container reuse in `local-worker.sh start` does not automatically replace an old container or install new tools.

## HTTP protocol

For the local API, set `CAPTURE_VIDEO_DIR` to an absolute private path (e.g. `/home/omar/Desktop/Dish3d/.data/capture-videos`). The worker must see the **same storage contents**. Container paths may differ, as keys are relative. An S3-compatible implementation can implement `CaptureBlobStore` without changing reconstruction logic; no S3 adapter or credentials are shipped in this milestone.

1. `POST /api/scans` with JSON `{ "dishId": "...", "sourceType": "video", "captureMetadata": { ... } }` using existing session authentication and Origin rules. Native pairing can create its usual empty scan; its first ordered frame/raw-video upload marks it schema 2.
2. Raw mode: `POST /api/scans/:id/video` or capability-authenticated `/api/native/video`. Body is the original file stream. Require `Content-Type: video/mp4` or `video/quicktime` and `X-Content-SHA256`. Receipt returns `validation: "pending_worker_decode"`, not reconstruction success. Repeating identical content deduplicates; a different video or mixed frame/video input is rejected.
3. Alternatively, upload individual frames to the existing frame endpoint with `X-Frame-Metadata` containing JSON: `{"frameIndex":0,"timestampMs":0,"intrinsics":{"fx":1200,"fy":1200,"cx":960,"cy":540,"referenceWidth":1920,"referenceHeight":1080},"cameraDevice":"...","lens":"...","orientation":1}`. Real dimensions are read from image bytes. Index reuse with different bytes or metadata is a 409. Arrival order does not matter; finalization requires consistent temporal order. Metadata is bounded to 16 KiB; it is preserved, not assumed geometrically correct.
4. Call the existing finalize endpoint. It freezes the schema-2 identity and uses the existing automatic reconstruction queue. A raw video can finalize with zero database frames, since the worker will extract them.
5. Poll/download with the existing reconstruction APIs. A decode error becomes a specific job error. GLB/USDZ still require complete export verification and fenced completion.

Old photo clients send no new header and continue using schema 1. The current TestFlight app is one of these clients; a native transfer update is a later integration task. Do not infer that it already sends calibration data.

**Vercel:** raw upload explicitly returns `VIDEO_STORAGE_UNAVAILABLE` there, because local ephemeral storage cannot be shared with the PC. Selected-frame/photo routes remain supported. Direct object-store upload is needed before offering raw video through the deployed site. This milestone creates the local raw-video backend; it does not pretend a 256-MiB body can transit an ordinary Vercel function.

## Identity and outputs

Schema 2 binds frame index, true timestamp, SHA, dimensions and camera metadata, plus capture metadata hash. Raw-input jobs instead bind immutable video SHA/size/MIME and capture metadata before frames exist. Their derived `frames_manifest.json` records every selected frame, original presentation index, actual PTS, dimensions and SHA plus extractor/tool identities. Frame order is never derived from SHA for videos.

```text
output/
  manifest.json                    # state, engine, inputs, output checksums, failures
  input/
    source.video                   # preserved original for raw video runs
    video_header.json
    ffprobe.json                    # full retained container/stream metadata + real frame times
    video_metadata.json
    frames_manifest.json
    capture_manifest.json           # when invoked by worker with scan sidecar
    camera_metadata.json            # supplied metadata; original reference coordinates
  frames/selected/000000.png         # lossless extracted frame, rotated/scaled with recorded size
  images/0000.jpg                    # unchanged legacy preparation
  sparse/, dense/, ...              # unchanged geometry intermediates
  model.glb
  model.usdz
  *.log
```

No output is called reconstructed in `--prepare-video` mode. No scale or quality certification is added. Successful geometry jobs still end as `ready_for_review`.

## Verification and performance

Final verification: `npm run check` passed (type generation, TypeScript, 32 Node tests). Python unittest passed 31 tests, including real FFmpeg decoding and the frozen legacy command comparison. A complete legacy reconstruction on 11 existing scan images at long-edge 800 px finished as `ready_for_review` in 307.680 seconds and produced structurally validated GLB/USDZ, with Blender texture round trips. See `docs/milestone1-verification.json` for sizes, hashes and observed child peak RSS. This reduced-resolution smoke is not a fair speed/quality comparison with the earlier 1600-px reconstruction (680.230 seconds); settings differ. Synthetic FFmpeg fixtures validate transport/decoding only; they are never evidence of photorealistic food reconstruction.

Resource limits remain: one globally leased heavy job, one CPU thread per engine, existing RSS/disk/stage-time guards, 3–40 input views under the legacy budget. Raw input is capped at 256 MiB, 120 seconds, 120 fps, 4096 pixels per side/9 MP, H.264 or HEVC in a self-contained MP4/MOV. These are safety ceilings, **not prescribed capture duration or quality recommendations**. Probe checks header bounds before full decoding. No all-frames image array is kept in memory; ffprobe timeline metadata is capped at 8 MiB and frame files stay on disk.

Compared with photos, raw video adds header probing, two complete video decode passes (timeline and actual PNG extraction), streaming hashing/copying and private original storage. Only the configured frame budget reaches COLMAP. Mesh commands/quality remain unchanged. The output retains an original copy plus selected PNGs, so disk use is higher. Exact reproducibility is scoped to the same decoder binary/build and settings; versions and binary hashes are recorded rather than assuming all FFmpeg builds are equivalent.

## Remaining milestones and limits

- Temporal quantiles are a deterministic baseline; **not** blur/exposure/duplicate/viewpoint selection. Identical pixels at separate timestamps remain distinguishable. Smart selection/reporting is milestone 2.
- No SAM2, COLMAP 4.2, OpenMVS 2.4, VGGT, gsplat, held-out rendering, physical scale inference or new reconstruction QA is enabled.
- No generated unseen geometry; incomplete capture can still yield an incomplete or poor legacy mesh.
- Supplied intrinsics/poses/depth fields and raw video orientation/color tags are preserved; the legacy geometry algorithm does not use them yet. Missing intrinsics are explicitly `UNAVAILABLE`. Lens-change detection/calibration and native sensor acquisition are later work.
- HDR tone mapping is not validated; retaining HDR metadata does not certify color fidelity after legacy JPEG preparation.
- Raw-frame sequence metadata is persisted in the worker output, not inserted as hundreds of PostgreSQL frame records.
- Originals are not deleted automatically. Operators must budget long-term storage. Rejected transport uploads are removed; failed worker attempts retain logs and input evidence.
- S3/object storage and native raw-video client wiring remain absent. This does not provide raw uploads from Vercel to the laptop yet.

## Deployment verification follow-up

The production build passed at 735 MiB peak sampled RSS. The HTTP-only smoke passed against an isolated local PGlite database: real ordered image upload, retries/conflicts, temporal retrieval, immutable finalization, real MP4 upload, checksum rejection, authentication, deduplication, mixed-source rejection, and native pairing/video/finalization. Its task peak was 1,094 MiB.

GitHub run `36205130522` could not start any verification step because GitHub reported failed recent account payments or an insufficient spending limit. Automatic deployment was skipped. The workflow is configured, but requires the account billing issue to be resolved.

Full browser regression was **not** revalidated here. Bundled Playwright browsers are absent on the PC; using installed Chrome passed the first capture scenario, then the existing memory supervisor stopped the combined batch. No UI code changed. The backend HTTP check above is the targeted deployment evidence; it is not represented as a full browser-suite pass. The production dependency audit passed the existing high-severity threshold but reported the pre-existing moderate `fflate` advisory GHSA-px8p-9vwx-vf98; no dependency upgrade was bundled into this reconstruction milestone.
