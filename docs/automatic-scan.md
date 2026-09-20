# Automatic dish scan and reconstruction on the owner's PC

## Guided scan (0.4)

**Scan your dish** opens a camera above a provisional 3D preview (side by side in landscape). Keep a stationary, well-lit plate in view and follow the orange arc. Accepted views turn mint; gray sectors remain unobserved. Raise the phone gently during the second half of the orbit. Coverage, directional hints and completion use saved ARKit camera observations, not elapsed time. No repeated shutter action, photo quota or photo counter is shown.

Foreground segmentation selects a central instance, including objects whose exact center has no foreground label. It is not a food classifier. Two stable raycasts locate a horizontal surface and anchor a bounded capture volume. After four seconds of unsuccessful detection, **Center scan here** allows explicit placement using a raycast or a provisional volume 45 cm in front of the camera. Estimated placement is labelled; it is not evidence of detected food, depth or verified scale. Normal ARKit tracking is still needed. The video alternative works without spatial tracking.

Analysis runs on one serial queue, at most once every 350 ms, with one retained ARFrame. Exposure, sharpness, tracking, motion, framing, translation and new angular coverage gate keyframes. Segmentation failure after anchoring does not indefinitely block otherwise useful views. Internally, coverage has 12 angular sectors, four elevated observations and a hard cap of 24 saved views. A rising orbit can finish with 12 views; missing sectors or top views remain highlighted. Automatic review requires all sectors and enough elevated views. The 8–20 second brief is a UX target, not a tested timing guarantee or a forced stop.

### Progressive preview choices

| Option | Implementation / decision |
| --- | --- |
| A — live points | Actual ARKit feature points, or scene-depth samples where supported, clipped to the dish volume. Observed camera colors are sampled where available; unsampled points retain a neutral tint. |
| B — coarse depth mesh | On devices supporting scene reconstruction, actual ARMeshAnchor triangles are clipped to the capture volume. Preview updates at most once per second, examines at most 60,000 faces and displays at most 4,000 triangles. It can include table fragments and cannot certify detailed food geometry. |
| C — Gaussian splats | No local splat training is included. It would require a separate calibrated multi-view optimizer and physical-device performance evaluation; animating invented splats would not demonstrate reconstruction. |
| D — silhouette volume | Standard phones combine foreground masks and actual camera poses in a bounded 32³ voxel visual hull. It starts after at least three distinct viewpoints and samples source colors. This is a soft silhouette estimate, unable to recover hidden concavities, not measured depth. |

Capabilities are selected at runtime: RGB/poses/segmentation → silhouette estimate; scene depth → measured points; supported LiDAR scene reconstruction → measured surface. Initial tracked points or the first saved camera image provide immediate evidence before a volumetric estimate exists. The image placeholder is explicitly labelled as a saved view. Unsupported or empty segmentation never fabricates a 3D model.

Preview geometry crossfades between actual updates, rotates slowly during capture and becomes orbit/zoom interactive in review. Haptics mark coverage milestones and completion. **Continue** sends the saved views when linked; **Scan a missing area** resumes the same coordinate system; **Restart** archives the old views under `Retakes` before resetting tracking. Closing/interruption preserves saved images. A session lost after app termination requires a fresh scan; original records remain available.

The local `preview.json` is explicitly provisional, with `finalModel=false` and `metricScaleVerified=false`. Camera intrinsics, poses and applied image orientation are saved with keyframes. The current PC worker recalibrates the uploaded JPEGs; it does not yet consume those native poses for automatic metric scaling. Review final shape, orientation and scale before publication. The browser viewer and iPhone Quick Look use the final GLB/USDZ, not the silhouette preview.

## Video alternative (available since 0.3)

Under **Other capture methods**, **Film your dish** opens a normal rear camera; recording never waits for foreground recognition, a horizontal plane, LiDAR or Object Capture support. Press **Record**, move slowly around a stationary, well-lit dish for roughly 20–40 seconds, finish from a slightly higher view, and press **Stop and use video**. Keep the entire plate visible and the phone in the same orientation. The timer is elapsed recording time, not measured coverage. Recording stops at 60 seconds or 180 MiB, and has no microphone/audio input.

The app saves the original movie in its capture folder, then extracts at most 24 upright JPEGs (1600 px maximum edge), sequentially on the phone. It examines two nearby samples per time slot, favors sharper views and rejects very dark, clipped, blurred or near-identical images. A minimum of eight usable, different images is required. These image checks cannot certify a complete orbit, food fidelity or successful photogrammetry. A static video is not a usable multi-view capture.

**Use an existing video** imports a file through the system picker without loading the entire movie into memory. Input is limited to 5–90 seconds and 250 MiB. Photo import remains available. The original video stays on the phone; only the selected JPEGs enter the existing transfer pipeline. A failed conversion exposes no partial photo set for upload. **Watch saved video** and **Retry preparing this video** allow review and recovery without filming again. Old capture records remain readable.

After linking a dish with its private website code, successful preparation starts photo upload automatically. Photos are sent one at a time and deduplicated. Finalizing requests reconstruction on the owner's PC, and the app downloads the verified USDZ when ready. If no dish is linked, the capture remains local and the app prompts for the code. Backgrounding stops recording and preserves a successfully finished movie; keep the app open during extraction and transfer. A saved video can be reprocessed if the OS terminates preparation.

## PC computation

There is no paid cloud reconstruction service. The PC consumes the existing PostgreSQL queue through an outbound connection; no router port or incoming PC endpoint is needed. New jobs wait durably while the PC is offline or lacks free RAM. Final model parts are returned privately through PostgreSQL, in 1 MiB responses, to fit Vercel limits. The app verifies the USDZ length and SHA-256 before opening the locally saved result. The owner can download GLB/USDZ from the website. Publication remains a separate review action.

The Docker image is compiled on GitHub from pinned COLMAP 3.11.1, OpenMVS 2.3.0 and Blender 4.5.13 sources/distribution. This avoids compilation on the 8 GB laptop. The container runs with one CPU, **1.5 GiB total hard RAM cap, no extra swap**, at most 256 processes, a read-only root, no elevated capabilities, no exposed ports, and only its own working directory writable. The default engine budget is 1 GiB. Node supervises one global job, samples engine RSS, stops under host memory pressure and applies per-job time/disk limits. Engine virtual address-space limits are replaced by the kernel RAM cap only when a <=2 GiB cgroup limit is actually present. CPU, file and disk guards remain.

The private `.data/worker.env` file contains only the authorized database connection and the reconstruction flag, is mode 0600 and is excluded from Git. Source photos remain on the phone and in the private restaurant account.

```bash
bash scripts/local-worker.sh start
bash scripts/local-worker.sh status
bash scripts/local-worker.sh logs
bash scripts/local-worker.sh stop
```

The service waits for memory cap + 1 GiB of free RAM before claiming a job. The PC must stay awake and connected. A container memory ceiling may reject a complex reconstruction; it is intentionally not raised automatically.

## Evidence and acceptance

Hosted macOS CI checks the unsigned Xcode archive and spatial coverage logic. The video suite encodes and decodes actual MOV files, checking orientation, bounded photo selection, stationary/dark/short rejection, preservation of the source and protection against overwriting saved images. Database tests exercise offline admission/deduplication, tenant isolation, cancelled/stale leases, and private artifact delivery. These checks do not establish physical camera tracking, speed, surface quality, metric scale or food fidelity. A real iPhone video capture was uploaded and reconstructed on 2026-09-20 (see below). Guided-camera behavior, final food fidelity, scale and physical AR placement still require device acceptance.

Apple references: [ARFrame raw feature points](https://developer.apple.com/documentation/arkit/arframe/rawfeaturepoints), [scene depth](https://developer.apple.com/documentation/arkit/arframe/scenedepth), [foreground instance masks](https://developer.apple.com/documentation/vision/vngenerateforegroundinstancemaskrequest). These APIs do not promise that raw feature points describe a complete object surface.

### Installed toolchain verification (2026-09-20)

The [hosted toolchain build](https://github.com/Omazi/dishplay3d/actions/runs/35531822310) succeeded. Its 748 MiB image archive was downloaded, SHA-256 checked and installed on the owner's Ubuntu PC. The reference dataset is [openMVG/ImageDataset_SceauxCastle](https://github.com/openMVG/ImageDataset_SceauxCastle/tree/fde7f5faba555e3c54700477c304488613346a19), pinned to `fde7f5faba555e3c54700477c304488613346a19`, with all 11 photos, 1600 px input, one CPU and a 1536 MiB container cap.

Actual execution exposed and fixed two OpenMVS interface/export issues: mesh stages produce separate PLY geometry while retaining camera poses in `dense.mvs`; the pinned OBJ exporter crashes for a single atlas, so the pipeline uses OpenMVS's native GLB export. Blender converts the imported unlit atlas material to a matte Principled surface so USD Preview Surface retains its actual image texture. Geometry and UVs remain from the reconstruction.

After resuming from the computed intermediates, every stage executed successfully and both final files passed structural checks and Blender reimport checks: GLB 10,310,168 bytes and USDZ 8,774,527 bytes. The export report records 43,404 faces and a readable texture in both formats. Local evidence is private under `.data/worker-validation/run-01/` (the original failure logs and continuation reports are retained). This is a building reference test; it does not establish food fidelity, metric scale, or iPhone Quick Look behavior.

The [web validation and deployment](https://github.com/Omazi/dishplay3d/actions/runs/35532964910) passed all 23 browser checks, including FR/EN, three original photo effects, three real illustrative GLBs, mobile layout and native transfer. The current TestFlight release is recorded in [the installation guide](testflight.md).

## Video release evidence

[TestFlight 0.3.0 (5.1)](https://github.com/Omazi/dishplay3d/actions/runs/35536319612), source `b03d671`, passed real movie extraction tests, unsigned and signed Xcode 26.3 archives, resource validation and Apple upload. Apple reports build `733cdfa6-e889-4d15-9285-90312db794ce` as `VALID` / `IN_BETA_TESTING`. It is assigned to the existing internal iPhone group with FR/EN notes and automatic notifications disabled. The user subsequently confirmed that video recording starts and completed a real upload; final fidelity and physical AR placement still require review.

## Actual iPhone upload evidence (2026-09-20)

The user’s paired video capture reached the durable queue and finished with `ready_for_review`, attempt 1, no error. PC computation ran from 21:05:41 to 21:21:30 UTC (about 16 minutes), under the existing one-CPU / 1536 MiB cap. This verifies the real upload → PC → final-artifact path. It does not prove that the model faithfully reproduces the dish or that AR scale has been checked on the phone. No user photos or credentials are included in these notes.

## Guided-scan automated acceptance

The hosted Mac suite projects a synthetic sphere through known camera poses, integrates its real generated silhouettes and verifies a bounded colored hull near the ground-truth shape. It rejects repeated, blank and whole-frame masks, checks behind-camera rejection and top-left raster coordinates. Coverage tests reject stationary/rapid views, preserve holes, require elevated coverage and follow either orbit direction. Real-MOV extraction regression tests remain in place. These mathematical/file checks and an unsigned/signed archive cannot replace a physical scan on a standard iPhone and a LiDAR iPhone.

The [0.4.0 (6.1) signed release](https://github.com/Omazi/dishplay3d/actions/runs/35539142553), source `695fb9b`, passed all native suites, archive/resource checks, signing and upload. Apple confirms `bcdfc99e-6374-4e0b-b76b-9122c8b20813` as `VALID` / `IN_BETA_TESTING`, assigned to the existing internal group with automatic notifications disabled. The [unsigned build](https://github.com/Omazi/dishplay3d/actions/runs/35539020255) also passed. Physical acceptance of this new guided flow remains pending.
