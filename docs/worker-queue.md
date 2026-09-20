# Opt-in PostgreSQL reconstruction worker

> **Updated automatic scan / PC workflow:** see [automatic-scan.md](automatic-scan.md). The earlier implementation notes below describe the original opt-in/manual workflow; the current app uses simple video capture, automatic photo preparation and queue submission, and private result downloads; ARKit capture remains an advanced option. Physical food reconstruction acceptance is still required.

The web application now has a durable queue and an independently started Linux worker. The feature is **off by default**. No engine is launched by opening a menu, editing a price, viewing 3D, or running the Next.js server. No paid compute is provisioned.

The queue state/fencing tests run against an isolated PostgreSQL-compatible PGlite database. They do not validate the COLMAP/OpenMVS/Blender pipeline, reconstruction fidelity, physical scale, or iPhone/Android output. The real engines have not been executed in this delivery environment. See [reconstruction.md](./reconstruction.md) for engine setup, pins, licenses and the separate real-dish acceptance work.

## Components

| Component                                 | Responsibility                                                                                        |
| ----------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `src/lib/server/jobs.ts`                  | Input/settings identity, queue admission, claims, leases, fencing, cancellation and review state      |
| `migrations/002_reconstruction_queue.sql` | Additive queue upgrade, worker heartbeat registry, singleton capacity row                             |
| `scripts/worker.ts`                       | Direct PostgreSQL consumer, private image materialization, supervised Python execution, output checks |
| `worker/reconstruct.py`                   | Bounded CPU reconstruction, actual stage manifest, GLB/USDZ validation                                |
| `/api/reconstruction`                     | Account-scoped requests and status; never executes the engine                                         |

The worker connects directly to the same PostgreSQL database as the web deployment. It does not expose an unauthenticated worker HTTP endpoint or use the embedded local PGlite data directory. Treat its database credentials as operator credentials. Engines receive a restricted environment without `DATABASE_URL` or other application secrets.

## Operator setup

1. Configure `DATABASE_URL` for both the web deployment and the worker. Keep the local worker's credentials outside the repository. Use the same database and schema.
2. Install the explicitly reviewed native toolchain and Python environment described in [reconstruction.md](./reconstruction.md). Nothing here installs those tools automatically. `npm ci` supplies the Node dependencies and TypeScript loader; the runner requires Node 24 and Linux.
3. Set `ENABLE_RECONSTRUCTION=true` in both environments. Enabling this variable on Vercel does not start compute there.
4. On the dedicated worker machine, set `WORKER_PYTHON` if using a virtual environment, then run `npm run worker:serve` from the repository root. This is an explicitly requested compute service: once running and healthy, it can consume jobs submitted by restaurant owners.
5. Confirm the worker startup succeeds and the restaurant's reconstruction panel reports an available worker. Startup runs the passive `--doctor` check and verifies the configured toolchain pins, presence of every binary, and Pillow metadata. Each actual job separately checks the installed binary versions before reconstruction.

There is no billing or GPU allocation step. Do not start a heavy reconstruction while also building the web project on an 8 GB laptop. Prefer a separate worker machine for the eventual restaurant service.

### Worker configuration

| Variable                    | Default / bounds                                                                                        |
| --------------------------- | ------------------------------------------------------------------------------------------------------- |
| `ENABLE_RECONSTRUCTION`     | Must be exactly `true`                                                                                  |
| `DATABASE_URL`              | Required PostgreSQL connection string                                                                   |
| `WORKER_PYTHON`             | `python3`; may point at an isolated environment's interpreter                                           |
| `WORKER_DATA_DIR`           | `.data/worker`; private local originals, logs and outputs                                               |
| `WORKER_MAX_IMAGES`         | 24; 3–40                                                                                                |
| `WORKER_LONG_EDGE`          | 1600 pixels; 320–1600                                                                                   |
| `WORKER_MEMORY_MIB`         | 1536; 512–2048                                                                                          |
| `WORKER_DISK_MIB`           | 2048; 256–4096                                                                                          |
| `WORKER_STAGE_SECONDS`      | 900; 30–1800 per stage                                                                                  |
| `WORKER_JOB_SECONDS`        | 3600; 60–10800 for the complete job                                                                     |
| `WORKER_OPENMVS_CUDA_BUILD` | `false`; use `true` only for a CUDA-enabled OpenMVS build that supports the explicit CPU selection flag |

The limits advertised in the heartbeat are the maximum settings that worker accepts. The web request defaults match the conservative 24-image, 1536 MiB configuration. The engine still uses CPU only, even if the build includes CUDA support.

The worker waits without claiming jobs unless available memory exceeds its configured cap plus 1024 MiB. During execution it samples the Python/engine descendant processes every two seconds, stops its own task if their combined RSS exceeds the configured cap plus 512 MiB or available system memory falls below 512 MiB, and imposes a total wall-clock budget. The Python runner also applies per-engine Linux address-space, file-size, CPU-time and disk guards. These are protective bounds, not measured promises that every dish will fit. One valid heavy-task lease is permitted globally.

## API

All routes require the normal restaurant session. Mutations require the same-origin `Origin` header.

### Request

```http
POST /api/reconstruction
Content-Type: application/json
Origin: https://your-app.example
```

```json
{
  "scanId": "finalized-capture-id",
  "settings": {
    "maxImages": 24,
    "longEdge": 1600,
    "memoryMiB": 1536,
    "diskMiB": 2048,
    "stageSeconds": 900,
    "scaleMetersPerUnit": null,
    "scaleReference": null,
    "openMvsCudaBuild": false
  }
}
```

`settings` is optional. Unknown settings are rejected; no executable arguments or download URLs can be supplied. An optional measured scale and its explanatory reference must be supplied together. They do not mark the output's scale verified.

Admission requires:

- `ENABLE_RECONSTRUCTION=true`, a real PostgreSQL `DATABASE_URL`, and a compatible worker whose heartbeat is less than 45 seconds old.
- An owned, finalized scan whose stored manifest still matches its frame hashes.
- Between 3 and the requested maximum number of distinct JPEG/PNG photos. A 25-photo capture does not silently become a 24-photo job. WebP originals remain safely stored but this engine path requires a separate JPEG/PNG capture.
- Fewer than three pending jobs for the restaurant, unless this request already has an identical job.

Success is `202 {id,state,deduplicated}`. Identity combines the immutable input manifest, pinned engine identity and normalized settings, and deduplicates within a restaurant. Repeating an existing request returns that job's state, including terminal failure/cancellation; it does not repeatedly spend compute. To change inputs, create a new capture. There is no user-facing retry endpoint for an unchanged permanently failed job; an operator should first diagnose it.

Without a recent compatible worker, the request returns `503 WORKER_UNAVAILABLE` and stores no job. The existing dish model and every original remain untouched.

### Status and cancellation

| Route                             | Result                                                       |
| --------------------------------- | ------------------------------------------------------------ |
| `GET /api/reconstruction`         | `{jobs,enabled,workerAvailable}`; latest 100 owned jobs      |
| `GET /api/reconstruction/{id}`    | `{job}`; inaccessible IDs return 404                         |
| `DELETE /api/reconstruction/{id}` | `{job,originalsPreserved:true}`; cancels queued/running work |

Job states are `queued`, `running`, `ready_for_review`, `failed`, and `cancelled`; the original schema's `succeeded` value remains readable for compatibility but this worker completes to `ready_for_review`. `stage` is the supervisor's actual input-materialization/preflight/export-validation step or the running Python manifest's actual stage. No percentage, point cloud or estimated completion is fabricated.

Jobs expose attempts, the maximum of two attempts, error code, timestamps, and a sanitized review summary. Database result records also keep a private output directory and full execution manifest; the HTTP response never exposes those private paths or credentials.

## Claims, leases and retries

Each claim briefly locks a singleton capacity row and selects queued work with `FOR UPDATE SKIP LOCKED`. This reserves one global heavy-task slot even when several workers are connected. A claim increments a generation and installs an unpredictable lease token. The lease lasts 90 seconds and renews every 10 seconds while processing; the capacity reservation lasts five seconds longer to allow process cleanup.

Every renewal, completion and failure checks the job ID, worker ID, generation, token, running state and unexpired database time. Cancellation invalidates the job token and increments the generation, but deliberately keeps the capacity slot occupied. The supervising worker releases that slot only after its process has exited; if the worker disappears, the reservation expires after its old lease plus cleanup grace. Stop acknowledgements also check the slot token/generation, so a stale worker cannot release a newer worker's reservation. A stale worker cannot mark an old attempt completed, overwrite a newer attempt or change a dish model.

Expired running leases are reclaimed only within the two-start attempt limit. An explicitly stopped worker may queue its interrupted attempt with a 30-second delay when budget remains. Engine/input/output failures are terminal by default so a deterministic error does not automatically repeat expensive work. If the database becomes unreachable, the worker stops its own subprocess; lease expiry provides bounded recovery.

SIGTERM/SIGINT stop the Python supervisor. Python treats SIGTERM as interruption, kills its active engine process group, and records cancellation in the local manifest. The Node supervisor has an additional kill fallback for currently observed descendants if Python fails to exit. Cancellation of a job becomes visible to the worker on its next renewal; already-produced local files are preserved, and their fenced result cannot be accepted after cancellation.

## Private inputs and review outputs

The worker materializes all frames one at a time into a mode-0700 job directory with mode-0600 files, verifies byte counts and SHA-256 hashes, and never changes the database originals. Each attempt gets its own directory and starts the Python runner with argument arrays and no shell.

A successful Python process must produce a real `ready_for_review` manifest plus the actual `model.glb` and `model.usdz`. The bridge independently checks file existence, regular-file status, bounded size, input association and output hashes against that manifest before a fenced completion. The Python pipeline performs the structural texture/geometry checks described in the reconstruction guide.

`ready_for_review` does **not** mean dish fidelity, metric scale, browser rendering or physical AR have passed. The operator must inspect the private files and complete the recorded review checklist, including a real Android and iPhone. No output URL is fabricated, no model is assigned to a dish, and no menu is published automatically.

To publish an approved model today, explicitly place its exports in operator-managed HTTPS asset storage, configure `MEDIA_PUBLIC_ORIGIN`, assign those public artifact URLs to the dish, and then publish the menu. Automated object-storage export, in-browser download of the worker's private local outputs, and a human approval endpoint are not implemented.

Retain or remove local worker directories according to an explicit backup/retention policy. The bridge does not silently delete failed attempts, captured originals or review outputs.

Database capacity and direct parent-death signals are not complete operating-system containment. A deliberately frozen process (`SIGSTOP`) cannot react to a signal until resumed, and arbitrary grandchildren may require a deployment cgroup or service supervisor. The Python per-user file lock is an additional same-host backstop. Run the production worker under an OS service/cgroup policy before relying on recovery from forced freezes or arbitrary process-tree failures.

## Verification performed

`node --max-old-space-size=256 --import tsx tests/jobs.test.ts` passed five tests against isolated in-memory PGlite:

- Restaurant-scoped deduplication and settings identity.
- Owned finalized inputs, fresh worker readiness and exact frame budgets.
- One global lease, renewal, expiry reclamation and stale completion/failure fencing.
- Cancellation preserving originals and the previous model, with capacity held until stop acknowledgement.
- Two-attempt limit, delayed retries and private output-path exclusion.

These use synthetic database records for state-machine tests. They do not run the worker service, COLMAP, OpenMVS, Blender or a real food reconstruction. Full PostgreSQL multi-process recovery and a complete engine run remain required operator acceptance checks.
