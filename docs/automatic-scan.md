# Automatic dish scan and reconstruction on the owner's PC

## Current flow

DishPlay Capture 0.2 uses ARKit world tracking, independently of Object Capture support. Tap **Scan your dish**. Vision segments the central foreground instance; repeated stable raycasts against a detected horizontal table plane locate a provisional capture volume. This is foreground detection, not a trained food classifier. Keep the dish still and in the frame.

The camera samples at most one analysis every 350 ms, with one retained ARFrame and one serial image analysis. Image sharpness, brightness, clipped pixels, camera motion, target visibility and new angular coverage gate saved keyframes. No shutter sequence or target photo count is shown. A rising orbit is suggested. Accepted observations fill 18 angular sectors; at least four elevated views are required. Coverage is calculated from accepted camera poses, never elapsed time. The internal cap is 24 views. Completion is automatic only when all required sectors pass. Actual duration and reconstruction success depend on the scene; 8–20 seconds is a UX goal, not an established result.

The lower panel shows actual ARKit feature points inside the provisional volume; supported scene depth adds measured points. It is labelled **Observed points · provisional**. It is not a textured mesh, silhouette volume or final reconstruction. Standard ARKit devices can produce sparse previews. LiDAR improves point density. A separate coarse mesh / splat pipeline is not implemented. Review permits rotation/zoom and filling missing areas in the same live AR session. After app termination, start a new scan rather than merging incompatible world coordinate systems. Pause/background/relocalization preserve saved images.

Link a dish using its private website code. Continue from scan review to upload; or select existing photos. JPEG copies are sent one at a time and deduplicated. The last successful upload finalizes the capture and automatically requests reconstruction. A finalized capture can be reopened to check the result. The website also sends and finalizes a complete imported photo set automatically for a linked dish.

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

The unsigned Xcode build and pure Swift coverage checks pass on hosted macOS. Database tests exercise offline admission/deduplication, tenant isolation, cancelled/stale leases, and private artifact delivery. These checks do not establish physical camera tracking, speed, surface quality, metric scale or food fidelity. A real iPhone scan and reconstruction remain required acceptance checks. No production scan was available during initial integration.

Apple references: [ARFrame raw feature points](https://developer.apple.com/documentation/arkit/arframe/rawfeaturepoints), [scene depth](https://developer.apple.com/documentation/arkit/arframe/scenedepth), [foreground instance masks](https://developer.apple.com/documentation/vision/vngenerateforegroundinstancemaskrequest). These APIs do not promise that raw feature points describe a complete object surface.

### Installed toolchain verification (2026-09-20)

The [hosted toolchain build](https://github.com/Omazi/dishplay3d/actions/runs/35531822310) succeeded. Its 748 MiB image archive was downloaded, SHA-256 checked and installed on the owner's Ubuntu PC. The reference dataset is [openMVG/ImageDataset_SceauxCastle](https://github.com/openMVG/ImageDataset_SceauxCastle/tree/fde7f5faba555e3c54700477c304488613346a19), pinned to `fde7f5faba555e3c54700477c304488613346a19`, with all 11 photos, 1600 px input, one CPU and a 1536 MiB container cap.

Actual execution exposed and fixed two OpenMVS interface/export issues: mesh stages produce separate PLY geometry while retaining camera poses in `dense.mvs`; the pinned OBJ exporter crashes for a single atlas, so the pipeline uses OpenMVS's native GLB export. Blender converts the imported unlit atlas material to a matte Principled surface so USD Preview Surface retains its actual image texture. Geometry and UVs remain from the reconstruction.

After resuming from the computed intermediates, every stage executed successfully and both final files passed structural checks and Blender reimport checks: GLB 10,310,168 bytes and USDZ 8,774,527 bytes. The export report records 43,404 faces and a readable texture in both formats. Local evidence is private under `.data/worker-validation/run-01/` (the original failure logs and continuation reports are retained). This is a building reference test; it does not establish food fidelity, metric scale, or iPhone Quick Look behavior.

The [web validation and deployment](https://github.com/Omazi/dishplay3d/actions/runs/35532964910) passed all 23 browser checks, including FR/EN, three original photo effects, three real illustrative GLBs, mobile layout and native transfer. [TestFlight 0.2.0 (3.1)](testflight.md) is available to the existing internal group.
