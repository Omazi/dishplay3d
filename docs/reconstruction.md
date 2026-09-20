# Local reconstruction worker

> **Updated automatic scan / PC workflow:** see [automatic-scan.md](automatic-scan.md). The earlier implementation notes below describe the original opt-in/manual workflow; the current app uses guided ARKit capture with a provisional progressive preview, a video alternative, automatic queue submission and private result downloads. Physical food fidelity and scale acceptance are still required.

## Current evidence

The CLI, CPU-only command plan, input checks, limits, output validation and Blender export script are implemented. Only lightweight contract/rejection tests and `--doctor` have been executed. **No dish has been reconstructed with this repository.** COLMAP, OpenMVS and Blender were absent from the development laptop. There is no native capture build or physical iPhone/Android acceptance result.

This is an opt-in standalone worker. It is not attached to the web app or deployed into Vercel functions. PostgreSQL job leases, authenticated uploads, queue retries and a production worker service are outstanding. Menu visits, price changes and QR scans cannot start this CLI.

## Safe inspection

Python 3.10+ is required. These commands install nothing and launch no reconstruction engines:

```bash
python3 worker/reconstruct.py --doctor
python3 -m unittest discover -s worker/tests -v
python3 worker/reconstruct.py --plan --input /path/to/photos --output /path/to/new-job
```

`--plan` reads and hashes JPEG/PNG files, then prints the exact argument arrays. It does not decode photos, create an output directory, or claim engine availability. Inputs must contain 3–24 distinct images by default; an explicit `--max-images 40` raises that ceiling to 40. This small batch is a resource diagnostic, not a food-quality guarantee. Keep the original 80–150-view acquisition separately and select a representative subset yourself; the worker never silently discards views.

## Explicit execution on a prepared Linux machine

Prepare an isolated Python environment with `worker/requirements.txt`, then install the toolchain below through your normal package/build review. The repository does not download engines or start paid services. Do not build these engines on a memory-constrained laptop while the app build is running.

| Tool    | Pinned interface | Evidence                                                                                                                                                                                                                                                                                    |
| ------- | ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| COLMAP  | 3.11.1           | [Release](https://github.com/colmap/colmap/releases/tag/3.11.1), [registered options](https://github.com/colmap/colmap/blob/3.11.1/src/colmap/controllers/option_manager.cc)                                                                                                                |
| OpenMVS | 2.3.0            | [Release](https://github.com/cdcseacave/openMVS/releases/tag/v2.3.0), [CLI sources](https://github.com/cdcseacave/openMVS/tree/v2.3.0/apps)                                                                                                                                                 |
| Blender | 4.5.13 LTS       | [Release series](https://www.blender.org/releases/4-5/), [USD operator source](https://github.com/blender/blender/blob/v4.5.13/source/blender/editors/io/io_usd.cc), [glTF operator source](https://github.com/blender/blender/blob/v4.5.13/scripts/addons_core/io_scene_gltf2/__init__.py) |
| Pillow  | 12.3.0           | [Release/security notes](https://pillow.readthedocs.io/en/stable/releasenotes/12.3.0.html)                                                                                                                                                                                                  |

These are explicit compatibility pins, not a claim that every engine is the latest or that this combination has passed an end-to-end test. Current COLMAP documentation uses some renamed feature options; upgrading requires changing the command adapter and rerunning a genuine dataset. Binary hashes and version help output are recorded on each execution. A mismatch stops the job.

After checking RAM/disk availability, running the following command explicitly starts real computation:

```bash
python3 worker/reconstruct.py --run \
  --input /path/to/photos \
  --output /path/to/new-job \
  --restaurant your-private-restaurant-id
```

Use a CPU-only OpenMVS build by default. If your installation includes CUDA, add `--openmvs-cuda-build`; the plan then explicitly passes `--cuda-device -2` to select CPU processing. Preflight rejects a build/flag mismatch. GPU visibility is also disabled in the child environment.

## Resource controls for an 8 GB laptop

- One job per operating-system user, using a nonblocking lock across all output directories.
- One engine stage at a time, one thread, CPU only, lower process priority.
- Images resized in a private working directory to at most 1600 pixels on the long edge; original files are never modified or deleted. JPEG/PNG only; at most 24 megapixels, 25 MiB per file and 400 MiB per batch. Converted previews drop original metadata; originals retain it.
- Default child address-space limit: 1536 MiB; allowed maximum: 2048 MiB. Start requires that budget plus 1024 MiB of available memory. This conservative limit can make Blender or reconstruction fail; reduce the batch or use another machine instead of removing the limit.
- Default per-stage CPU/wall timeout: 900 seconds. A failed or cancelled process group is killed. No automatic retries.
- Default working-set disk cap: 2048 MiB, checked every second; 512 MiB maximum per output file; stop below 1024 MiB free disk or 512 MiB available RAM.

Disk polling is a soft aggregate limit and can overshoot between checks. POSIX address-space limits apply per process, not to the entire process tree. Use an OS/container memory and disk quota for a production service; this script is not an untrusted-file sandbox. Native libraries may reserve substantial virtual memory and exit under this conservative cap. These controls reduce resource pressure; they do not establish a measured peak for this unexecuted pipeline.

## Real stages and truthful state

1. Validate paths, signatures, size/count and distinct hashes; freeze an input/settings/engine identity scoped by restaurant.
2. Confirm installed engine versions and hash binaries; resize working copies with Pillow.
3. Extract SIFT features and match views on CPU; estimate cameras with COLMAP; undistort the registered reconstruction.
4. Import into OpenMVS; densify, reconstruct mesh, refine, texture, and retain the textured GLB, atlas and master intermediates.
5. Import the actual textured GLB into Blender and map its observed atlas to a USD-compatible matte material; export embedded GLB and USDZ; reimport both and check mesh faces, UVs and readable image materials.
6. Validate GLB framing, mesh/material/embedded texture references and USDZ packaging; record file hashes, sizes, real completed stages, elapsed time and child peak RSS.

A successful command ends at `ready_for_review`, never `published`. Failure preserves the inputs and all working files, with the failing stage/log named in `manifest.json`. Use a new output directory for another attempt; automatic checkpoint resume is not implemented. There is no generated point cloud, invented pose, simulated progress percentage, synthetic mesh, or fallback object.

The hashed identity supports deduplication by an eventual scheduler; this CLI does not provide a persistent cross-job cache. Its sparse-model assumption is one COLMAP reconstruction (`sparse/0`); disconnected or poorly registered views can fail and require recapture.

## Scale, orientation and publication

Uncalibrated photogrammetry has no proven metric scale. Exports default to their recovered units, with `scale_verified: false`. If independently calibrated, supply both `--scale-m-per-unit NUMBER` and `--scale-reference "measurement description"`; this records/applies the multiplier but still requires physical verification. The worker does not crop away the table, infer a plate diameter, invent hidden bowl contents, repair missing surfaces, or certify food fidelity.

Check model orientation and crop/scale manually before publication. Structural validation and Blender round trips do not prove correct colour, shape, texture coverage, Quick Look support, or AR dimensions. A poster renderer, measured simplification/mobile asset budgets and glTF Validator integration are still outstanding. Retain photo publication when any check fails.

## Licence boundary

COLMAP identifies its own licence as BSD; dependencies must be reviewed separately. OpenMVS is [AGPL-3.0](https://github.com/cdcseacave/openMVS/blob/v2.3.0/LICENSE). Blender is GPL-licensed. This repository invokes separately installed executables and does not redistribute them. Process separation alone is not a conclusion about licence obligations; review the actual distribution/service design before commercial operation.

## Acceptance evidence template

Complete this from an actual run; leave unknown fields blank:

```text
Date / operator:
Restaurant / dish / revision:
Capture phone / OS / camera mode:
Original view count / retained views / resolution:
Withheld validation views:
Lighting / reflective or transparent areas / bowl interior:
Worker machine / RAM / OS:
Engine versions + binary hashes / job manifest path:
Completed stages / failed stage and reason:
Elapsed seconds / observed peak RSS / disk usage:
GLB + USDZ hashes / byte sizes:
Known physical dimension / exported dimension / error:
Orientation / texture / portion review:
iPhone model + Safari/Quick Look result:
Android model + Chrome/Scene Viewer result:
QR destination before and after price edit:
Recovery after permission denial / interrupted upload:
Decision: photo only / recapture / reviewed model:
```

The dossier proposes ≥16 publishable dishes out of 20 after at most two acquisitions and ≤5% scale error. Those are acceptance targets, not measured results here.
