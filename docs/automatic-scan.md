# Automatic dish scan and reconstruction on the owner's PC

## Current flow

DishPlay Capture 0.2 uses ARKit world tracking, independently of Object Capture support. Tap **Scan your dish**. Vision segments the central foreground instance; repeated stable table raycasts locate a provisional capture volume. This is foreground detection, not a trained food classifier. Keep the dish still and in the frame.

The camera samples at most one analysis every 350 ms, with one retained ARFrame and one serial image analysis. Image sharpness, brightness, clipped pixels, camera motion, target visibility and new angular coverage gate saved keyframes. No shutter sequence or target photo count is shown. A rising orbit is suggested. Accepted observations fill 18 angular sectors; at least four elevated views are required. Coverage is calculated from accepted camera poses, never elapsed time. The internal cap is 24 views. Completion is automatic only when all required sectors pass. Actual duration and reconstruction success depend on the scene; 8–20 seconds is a UX goal, not an established result.

The lower panel shows actual ARKit feature points inside the provisional volume; supported scene depth adds measured points. It is labelled **Observed points · provisional**. It is not a textured mesh, silhouette volume or final reconstruction. Standard ARKit devices can produce sparse previews. LiDAR improves point density. A separate coarse mesh / splat pipeline is not implemented. Review permits rotation/zoom and filling missing areas in the same live AR session. After app termination, start a new scan rather than merging incompatible world coordinate systems. Pause/background/relocalization preserve saved images.

Link a dish using its private website code. Continue from scan review to upload; or select existing photos. JPEG copies are sent one at a time and deduplicated. The last successful upload finalizes the capture and automatically requests reconstruction. A finalized capture can be reopened to check the result. The website also sends and finalizes a complete imported photo set automatically for a linked dish.

## PC computation

There is no paid cloud reconstruction service. The PC consumes the existing PostgreSQL queue through an outbound connection; no router port or incoming PC endpoint is needed. New jobs wait durably while the PC is offline or lacks free RAM. Final model parts are returned privately through PostgreSQL, in 1 MiB responses, to fit Vercel limits. The app verifies the USDZ length and SHA-256 before opening the locally saved result. The owner can download GLB/USDZ from the website. Publication remains a separate review action.

The Docker image is compiled on GitHub from pinned COLMAP 3.11.1, OpenMVS 2.3.0 and Blender 4.5.13 sources/distribution. This avoids compilation on the 8 GB laptop. The container runs with one CPU, **2 GiB total hard RAM cap, no extra swap**, at most 256 processes, a read-only root, no elevated capabilities, no exposed ports, and only its own working directory writable. Node supervises one global job, samples engine RSS, stops under host memory pressure and applies per-job time/disk limits. Engine virtual address-space limits are replaced by the kernel RAM cap only when a <=2 GiB cgroup limit is actually present. CPU, file and disk guards remain.

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
