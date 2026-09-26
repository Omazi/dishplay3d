# Milestone 2 — input selection and masks

## Status: implemented for offline evaluation, acceptance benchmark incomplete

**Has intelligent selection measurably improved reconstruction of an actual dish? Not established.**

No original dish video has been identified/provided for this milestone. Existing scan folders contain extracted photos, which are not a substitute for the same-video experiment. Marketing videos and simulator recordings are not suitable captures. The available desktop RAM also fell below the reconstruction admission requirement during this session. No heavy reconstruction or SAM inference was launched under that pressure.

The implementation is an explicit `--selection-config` experiment. The production queue and iPhone upload path still use M1 behavior. Enabling a new preprocessing identity in the queue is deferred until the required reconstruction comparison supports promotion. COLMAP 3.11.1, exhaustive matching, OpenMVS 2.3.0, Blender 4.5.13, Pillow 12.3.0 and the existing GLB/USDZ export code remain unchanged.

## Actual evidence

Private local artifacts: `.data/milestone2/` (excluded from Git).

| Evidence | Temporal baseline | Smart selection |
| --- | --- | --- |
| Source | Same 40-frame synthetic translated texture, 320×240, 4 seconds | Same source SHA |
| Selected indices | 0, 5, 11, 16, 22, 27, 33, 39 | 0, 6, 13, 20, 27, 32, 34, 39 |
| Selected count | 8 | 8 |
| Preprocessing wall time, one diagnostic run | 11.59 s | 7.42 s |
| Self peak RSS | 73,684 KiB | 73,684 KiB |
| COLMAP registered images / ratio | **Not run** | **Not run** |
| Sparse points / reprojection error | **Not run** | **Not run** |
| OpenMVS / mesh / output sizes | **Not run** | **Not run** |
| Final rendered asset | **Unavailable** | **Unavailable** |

These timings include FFmpeg startup, timeline probing, extraction and analysis. The sequential fixture run shares a Python process and benefits from warm caches; they are not a speed benchmark. Outer sampled process-tree peak: 118 MiB. A separate supervised preprocessing integration reached `prepared_only`, with 99 MiB sampled peak. Its initial admission headroom was simulated for the tiny fixture; actual process limits and runtime memory-pressure checks remained active. This is **not permission to bypass the guard for real reconstruction**.

Artifacts for each method:

- `capture_report.json`: every candidate, quality metrics, rejection reasons, geometric pair measurements, selected score components, coverage limitations, timing and resource measurements.
- `contact_sheet_candidates.jpg`, `contact_sheet_selected.jpg`, `contact_sheet_masks.jpg`.
- `input/source.video`, `input/ffprobe.json`, `input/video_metadata.json`, `input/frames_manifest.json`, `input/selected_manifest.json`.
- `frames/candidates/` retains rejected RGBs; `frames/selected/` contains copies.
- Masks are explicitly unavailable in this fixture. The mask sheet labels that fact; it contains no invented segmentation.

Visual inspection of the selected sheet confirms chronological translated texture views. There is no food, volume, parallax ground truth or final 3D output in that fixture, so it cannot establish food fidelity.

The binary-metrics reader was additionally checked against an **old M1 photo reconstruction**: 11 registered images, 4,062 sparse points, mean point reprojection error 0.29656 px. These are parser-validation values, **not M2 benchmark results**.

## Algorithms and decisions

| Stage | Implementation / interpretation |
| --- | --- |
| Candidate extraction | Decode the entire validated video with bounded FFmpeg; save deterministic presentation-order samples. Union the candidate grid with exact M1 temporal quantiles so the baseline uses the same source indices as before. Candidate budget defaults to 150; union may add up to `final_count` samples (absolute maximum 280). |
| Sharpness | Laplacian variance plus mean Sobel gradient magnitude. Both must be low for `BLURRED_FRAME`. Analysis uses a common maximum edge so thresholds are comparable. |
| Motion blur | Gradient structure-tensor eigenvalue ratio plus high-frequency DCT energy. Directional edges can resemble blur: this is a replaceable heuristic, not a calibrated blur probability. |
| Exposure | Mean grayscale luminance, 1/10/50/90/99 percentiles, fraction ≥250 and ≤5. Hard rejection targets gross clipping/darkness; small bright highlights survive. RGB values are not enhanced or inpainted. |
| Exact duplicates | SHA-256 of full decoded RGB pixel values, distinct from the immutable video/capture hash. Late return views are exempted for potential loop closure. |
| Near duplicates | 63-bit pHash Hamming distance **and** low displacement of geometrically verified correspondences. Similar-looking frames with useful displacement survive. |
| Geometry | ORB at bounded resolution; Hamming matching, Lowe ratio and reciprocal match checks; deterministic RANSAC fundamental matrix and homography. The stronger support estimates overlap; homography support alone does not prove 3D parallax. Persist feature counts, matches, inliers, inlier ratio, inliers/min-feature-count overlap, normalized displacement and homography residual. |
| Selection | Ordered overlap graph, bounded beam search by terminal frame and count. Every edge must satisfy inlier count/ratio. Retain up to the requested count; prefer a full chain, then temporal extent, then composite utility. This ordering is itself an experimental choice to evaluate. |
| Utility | Weighted quality + displacement-band novelty + coverage gain − redundancy − frequency-blur proxy − crop. Save chosen contributions and best evaluated contributions/predecessor for rejected candidates. All tunable score weights and thresholds live in configuration. |
| Loop closure | Search late candidates that match the start and remain connected to the penultimate selected frame. A closure override is explicitly logged, not disguised as the highest utility. |
| Pose coverage | Accept finite rigid camera-to-world matrices with explicit convention, normal tracking, +Y world-up and supplied object center. Bucket approximate viewing position into azimuth/elevation. No fabricated camera pose or center. |
| No-pose coverage | Report sequence/matching diversity as a **low-confidence proxy**, angular bins `null`, and `captureSufficient: false`. No claim that a fixed number of seconds or turns is sufficient. |

RGB/global metrics are not semantic food recognition. With segmentation disabled, object visibility/crop remain `null`. With masks, visibility is a heuristic confidence and crop is border-contact fraction, not a measured percentage of missing plate.

## Segmentation

`DishSegmenter` separates the rest of the code from SAM. `SAM21Segmenter` uses the official video predictor, with point, box or automatic initialization. The canonical requested object is **food + plate, excluding table**.

Automatic proposals are ranked using SAM proposal stability/predicted IoU, center proximity, bounded area, bounding-box aspect and border contact. A close runner-up or low score fails as `SEGMENTATION_LOW_CONFIDENCE`. Propagation is checked for dimensions, one-object identity, position-to-frame mapping, temporal mask IoU, area and cropping. This heuristic can still choose an ingredient or miss a transparent plate: semantic correctness is not proven by a high score.

The official predictor eagerly loads video frames. To avoid retaining hundreds of 1024² float images on an 8GB laptop, the adapter uses windows of 8 candidates with a one-frame overlap. The last propagated mask seeds the next window. **Model temporal memory resets between windows**; this is recorded in `sam-provenance.json`. It must be evaluated against full-video propagation on a suitable machine before production promotion.

- Default requested SAM failure policy: fail, with a specific code.
- Optional `segmentation_fallback: "no-mask"`: explicitly recorded global no-mask baseline; partial masks are not passed to reconstruction.
- Experiment B refuses to proceed without valid masks even when fallback was requested.
- Saved masks are separate from RGB: `masks/candidates`, `masks/selected`, `masks/colmap`, `masks/undistorted`.
- Checkpoint SHA, config, CPU device, initialization and window behavior are recorded. No checkpoint is downloaded automatically.
- Real SAM inference **has not been tested here**: host PyTorch is 1.12 CPU, SAM is absent. Unit tests exercise the adapter protocol with a fake predictor, not a learned model.

## Mask experiments without upgrading OpenMVS

| Experiment | COLMAP | OpenMVS 2.3 |
| --- | --- | --- |
| `POSE_FULL__OBJECT_MASKED` | Unmodified RGB features | Undistorted dish masks, background label 0 |
| `POSE_MASKED__OBJECT_MASKED` | `--ImageReader.mask_path` foreground masks; overlap preflight also uses foreground features | Same downstream masks |

The installed OpenMVS 2.3 binary was checked: it supports `--mask-path` and `--ignore-mask-label`. Masks cannot simply be copied after RGB undistortion. The new adapter reads the actual source SIMPLE_RADIAL and destination PINHOLE calibrations, maps pixel centers (+0.5 convention), and resamples labels with nearest neighbors. Unsupported camera models/dimension mismatches fail rather than silently misalign.

COLMAP masks are named `0000.jpg.png`; OpenMVS masks are `0000.mask.png` (`Util::getFileName` strips the RGB extension). `mapping.json` records names, dimensions and labels. The report marks masks applied only after the corresponding engine stage completes. These commands are integrated but **the two full masked reconstruction experiments have not run**. Unit identity/scaling checks of the warp do not certify real dish segmentation or dense output.

## Reproduce the required benchmark

Use a separate Python 3.10–3.12 environment with `worker/requirements-selection.txt`. Native reconstruction tools must remain pinned. The optional `worker/container/Dockerfile.selection` extends the existing engine image with FFmpeg/CV dependencies; it does not rebuild or upgrade COLMAP/OpenMVS/Blender. This layer has not been built on the memory-constrained desktop.

From a bounded environment containing those dependencies:

```bash
python -m worker.benchmark \
  --video /private/original-dish.mov \
  --output /private/dish-comparison \
  --config worker/configs/smart-selection-v1.json \
  --counts 24 32 48 64 --long-edge 800 --memory-mib 1536
```

Runs are sequential, never concurrent. `reconstruct.py` keeps its singleton task lock, per-stage time/disk/CPU/memory limits and memory admission check. Prefer a container with `--cpus=1 --memory=1536m --memory-swap=1536m`, with an additional 1024 MiB host headroom. Do not disable guards to force the benchmark through desktop memory pressure.

Each run records real selected indices, reasons, COLMAP registration/ratio/sparse-point/reprojection metrics, OpenMVS stage success, timing, child peak RSS, GLB vertex/triangle counts and GLB/USDZ size. Binary digests must match between both methods. The Blender inspection script generates identical-style neutral renders and a side-by-side image; independent auto-framing is **not geometric alignment**. Human inspection must compare plate integrity, food shape, holes, floaters, table contamination and texture fidelity. More vertices or registered images alone do not prove fidelity.

Repeat with separate fresh output folders and SAM configs for experiments A/B after configuring a local official tiny checkpoint. Keep segmentation/settings identical between temporal/smart pairs. Compare masks versus no masks separately, avoiding a confounded selection claim.

SAM installation, when resources permit, is isolated and optional:

```bash
# In a new Python 3.10–3.12 venv only:
pip install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cpu
SAM2_BUILD_CUDA=0 pip install --no-build-isolation -r worker/requirements-sam2.txt
```

Set `sam_checkpoint` to an official SAM 2.1 tiny checkpoint and inspect the saved masks before accepting a reconstruction. Code revision is pinned in the requirements file; the actual checkpoint hash must be recorded from the supplied file. No real checkpoint has yet been installed or verified in this milestone.

## Minimal future native changes (no native files changed here)

1. `VideoFrameExtractor.swift` currently discards `AVAssetImageGenerator`'s actual returned time. Preserve actual PTS, preferred transform and decoded dimensions; requested sample time is not sufficient, especially with variable frame rate.
2. `CaptureTransfer.swift` uploads JPEGs and hashes, not the M1 complete raw-video format/metadata. Add a raw-video upload and the immutable sidecar, or ordered-frame headers carrying `frameIndex` and `timestampMs`. Retain originals and use the existing resumable/finalization semantics.
3. `GuidedScan.swift` already has `ARFrame.timestamp`, `camera.transform`, `camera.intrinsics`, image resolution and tracking state. Its saved schema-3 photo checkpoints contain **column-major flat arrays**, device-uptime timestamps and image orientation. They are not currently the new ordered video metadata. Convert explicitly to row-major 4×4 camera-to-world arrays for this selector, preserving the originals too.
4. `ScanMovieRecorder.swift` rebases accepted buffers to `timestamp - firstTime`, timebase 600, and may drop input frames. Emit metadata only after `adaptor.append` succeeds, with the resulting movie frame index/PTS and the corresponding ARFrame metadata. Do not associate dropped frames or uptime directly with normalized movie PTS.
5. Preserve calibration coordinates: intrinsics refer to sensor resolution. Record crop, resize and preferred-track orientation, and transform intrinsics when consuming decoded pixels. M2 does not feed these intrinsics into legacy COLMAP.
6. The plain `VideoCaptureScreen.swift` explicitly selects the rear wide-angle AVCaptureDevice, so its device type/lens identity can be recorded there. Imported MOV files may lack lens/calibration data; use `null`/unavailable. Ordinary AVFoundation recording does not supply ARKit pose or scene depth.
7. The ARKit path can record normal/limited tracking and `sceneDepth != nil`/confidence availability per frame. World-up can be declared +Y only when the configured tracking coordinate system warrants it. Physical gravity samples require an actual motion-data source and a synchronized timebase; do not invent a gravity vector from video RGB.
8. Save the selected capture volume's center (`ScanVolume.center`, distinct from its table-level `origin`), confidence/estimated status and pose reference. The center is an engineering estimate, not exact dish geometry. Relocalization/session resets must start a new pose reference or segment, not a continuous fabricated orbit.

Current optional sidecar contract: `captureMetadata.videoFrames[] = {frameIndex, timestampMs, metadata}`. Pose metadata needs `cameraTransform`, `poseConvention: "camera-to-world-row-major"`, `trackingState: "normal"`, `worldUp: "+Y"`, `objectCenterWorld`, and a stable `poseReference` session identifier. Mixed reference identifiers disable pose-based selection for that video. Matching uses exact frame index or a bounded actual-time gap; it does not interpolate missing poses. Intrinsics, orientation, lens, gravity and depth availability are preserved but are not yet independently weighted by the selector.

Prompt contract: `captureMetadata.segmentationPrompt = {coordinateSpace: "decoded-pixels", framePosition: 0, point: [x,y]}` or `box: [x0,y0,x1,y1]`. Prompt coordinates must refer to the first extracted candidate at its decoded resolution/orientation; the worker does not guess a sensor-to-decoded transform.

## Limitations and remaining acceptance work

- Supply original videos of several representative dishes. The same-video full reconstruction comparison and the 24/32/48/64 count sweep remain **not run**.
- Run actual SAM 2.1 inference and inspect plate semantics, auto-initialization ambiguity, window boundaries and failure rate.
- Run both mask experiments through the pinned engine; inspect undistorted overlays and final geometry.
- Tune thresholds on multiple captures, not the synthetic texture or a single successful dish.
- pHash and ORB struggle with smooth/glossy food; displacement includes camera rotation and is not parallax ground truth. An ordered, well-matched chain can still triangulate poorly.
- Conservative global low-confidence failure may reject a video because one propagated mask is uncertain. An improved recovery strategy requires actual capture evidence.
- Intrinsics/lens/gravity/depth are retained; only validated poses/tracking are currently used as additional geometric selection signals.
- No real-video side-by-side final renders exist yet. No production quality improvement, production activation or milestone completion is claimed.

## Primary implementation references

- [Official SAM2 video predictor and SAM 2.1 installation](https://github.com/facebookresearch/sam2/tree/2b90b9f5ceec907a1c18123530e92e794ad901a4).
- [COLMAP 3.11.1 image-mask naming](https://github.com/colmap/colmap/blob/3.11.1/src/colmap/controllers/image_reader.cc).
- [COLMAP pixel-center camera warp](https://github.com/colmap/colmap/blob/3.11.1/src/colmap/image/warp.cc).
- [OpenMVS 2.3 mask options](https://github.com/cdcseacave/openMVS/blob/v2.3.0/apps/DensifyPointCloud/DensifyPointCloud.cpp) and [mask basename behavior](https://github.com/cdcseacave/openMVS/blob/v2.3.0/libs/Common/Util.h).

The following generated appendices list every configuration value and changed file.


## All configurable defaults

These are experimental starting values, not validated production tuning. The JSON configs contain the same values.

| Setting | Default |
| --- | --- |
| `method` | `"SMART_SELECTION_V1"` |
| `candidate_count` | `150` |
| `final_count` | `32` |
| `minimum_count` | `8` |
| `analysis_edge` | `640` |
| `min_short_edge` | `200` |
| `min_laplacian` | `18.0` |
| `min_gradient` | `5.0` |
| `sharpness_saturation_multiple` | `8.0` |
| `min_high_frequency` | `0.025` |
| `max_directional_ratio` | `18.0` |
| `max_white_fraction` | `0.65` |
| `max_black_fraction` | `0.8` |
| `min_mean_luminance` | `12.0` |
| `max_mean_luminance` | `247.0` |
| `phash_distance` | `6` |
| `duplicate_displacement` | `0.004` |
| `min_novel_displacement` | `0.008` |
| `ideal_displacement` | `0.045` |
| `min_inliers` | `18` |
| `min_inlier_ratio` | `0.3` |
| `max_features` | `1200` |
| `match_ratio` | `0.75` |
| `ransac_pixels` | `2.5` |
| `lookahead` | `24` |
| `beam_width` | `2` |
| `quality_weight` | `1.0` |
| `novelty_weight` | `1.0` |
| `coverage_weight` | `0.7` |
| `redundancy_weight` | `0.8` |
| `crop_weight` | `1.0` |
| `blur_weight` | `0.5` |
| `segmentation` | `"none"` |
| `segmentation_fallback` | `"fail"` |
| `segmentation_init` | `"auto"` |
| `sam_checkpoint` | `null` |
| `sam_config` | `"configs/sam2.1/sam2.1_hiera_t.yaml"` |
| `sam_window` | `8` |
| `min_mask_confidence` | `0.65` |
| `min_auto_score_margin` | `0.05` |
| `auto_center_x` | `0.5` |
| `auto_center_y` | `0.55` |
| `auto_center_radius` | `0.65` |
| `auto_placement_base` | `0.7` |
| `auto_placement_weight` | `0.3` |
| `auto_border_penalty` | `4.0` |
| `min_mask_area` | `0.03` |
| `max_mask_area` | `0.8` |
| `max_border_fraction` | `0.08` |
| `min_mask_consistency` | `0.35` |
| `experiment` | `"POSE_FULL__OBJECT_MASKED"` |
| `azimuth_bins` | `8` |
| `required_azimuth_bins` | `6` |
| `pose_max_gap_ms` | `80.0` |
| `max_pose_distance_m` | `10.0` |
| `min_pose_distance_m` | `0.03` |

## Exact file map

- `docs/milestone2-verification.json` — created
- `.github/workflows/ci-cd.yml` — modified
- `docs/milestone2-input-quality.md` — created
- `worker/benchmark.py` — created
- `worker/colmap_artifacts.py` — created
- `worker/configs/sam21-pose-full.json` — created
- `worker/configs/sam21-pose-masked.json` — created
- `worker/configs/smart-selection-v1.json` — created
- `worker/container/Dockerfile.selection` — created
- `worker/frame_selection/__init__.py` — created
- `worker/frame_selection/artifacts.py` — created
- `worker/frame_selection/blur.py` — created
- `worker/frame_selection/coverage.py` — created
- `worker/frame_selection/exposure.py` — created
- `worker/frame_selection/models.py` — created
- `worker/frame_selection/overlap.py` — created
- `worker/frame_selection/quality.py` — created
- `worker/frame_selection/selector.py` — created
- `worker/frame_selection/similarity.py` — created
- `worker/preprocess.py` — created
- `worker/reconstruct.py` — modified
- `worker/render_benchmark.py` — created
- `worker/requirements-sam2.txt` — created
- `worker/requirements-selection.txt` — created
- `worker/segmentation/__init__.py` — created
- `worker/segmentation/base.py` — created
- `worker/segmentation/masks.py` — created
- `worker/segmentation/sam2.py` — created
- `worker/segmentation/undistort.py` — created
- `worker/tests/test_mask_geometry.py` — created
- `worker/tests/test_segmentation_fallback.py` — created
- `worker/tests/test_selection.py` — created
- `worker/tests/test_video.py` — modified
- `worker/video.py` — modified


## Verification results

- **58 Python tests passed**, including the frozen legacy command plan, photo workflow, video timestamps/order, duplicate pixels at distinct times, quality rejection, geometric matching, fake-predictor mask propagation, mask-coordinate warp, explicit segmentation fallback and pose-reference rejection. Latest suite: 47.496 s, 131 MiB sampled process-tree peak.
- **32 Node tests passed**, including immutable Manifest V1/V2 and queue/lease/upload compatibility. Sampled task peak: 747 MiB.
- The two small M1 CLI fixtures now simulate **initial** memory-admission headroom so desktop activity does not change contract-test outcomes. Runtime pressure checks remain real; a separate test asserts that insufficient headroom refuses the task before output creation. No production memory limit changed.
- The subprocess preprocessing integration reached `prepared_only` on the synthetic fixture. No GLB/USDZ is asserted or created by that test.
- Python syntax, workflow YAML parsing and `git diff --check` passed.
- Actual SAM checkpoint inference, the optional container build, full masked reconstruction, real-dish comparison, and final asset renders remain unverified. Unit results are not acceptance evidence for those items.
