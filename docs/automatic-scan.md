# Automatic dish scan and reconstruction on the owner's PC

## Video capture (0.3)

The primary iPhone action is **Film your dish**. It opens a normal rear camera; recording never waits for foreground recognition, a horizontal plane, LiDAR or Object Capture support. Press **Record**, move slowly around a stationary, well-lit dish for roughly 20–40 seconds, finish from a slightly higher view, and press **Stop and use video**. Keep the entire plate visible and the phone in the same orientation. The timer is elapsed recording time, not measured coverage. Recording stops at 60 seconds or 180 MiB, and has no microphone/audio input.

The app saves the original movie in its capture folder, then extracts at most 24 upright JPEGs (1600 px maximum edge), sequentially on the phone. It examines two nearby samples per time slot, favors sharper views and rejects very dark, clipped, blurred or near-identical images. A minimum of eight usable, different images is required. These image checks cannot certify a complete orbit, food fidelity or successful photogrammetry. A static video is not a usable multi-view capture.

**Use an existing video** imports a file through the system picker without loading the entire movie into memory. Input is limited to 5–90 seconds and 250 MiB. Photo import remains available. The original video stays on the phone; only the selected JPEGs enter the existing transfer pipeline. A failed conversion exposes no partial photo set for upload. **Watch saved video** and **Retry preparing this video** allow review and recovery without filming again. Old capture records remain readable.

After linking a dish with its private website code, successful preparation starts photo upload automatically. Photos are sent one at a time and deduplicated. Finalizing requests reconstruction on the owner's PC, and the app downloads the verified USDZ when ready. If no dish is linked, the capture remains local and the app prompts for the code. Backgrounding stops recording and preserves a successfully finished movie; keep the app open during extraction and transfer. A saved video can be reprocessed if the OS terminates preparation.

## Advanced spatial scan

The previous ARKit/Vision flow remains under **Advanced spatial scan**. It requires foreground segmentation and stable raycasts against a horizontal table before accepting views. If that detection gets stuck, return to the primary video mode. It is foreground detection, not a trained food classifier.

The camera samples at most once every 350 ms, with one retained ARFrame and one serial analysis. Sharpness, brightness, clipped pixels, motion, target visibility and new angular coverage gate saved keyframes. Accepted observations fill 18 angular sectors, with at least four elevated views and a cap of 24 photos. Coverage comes from accepted camera poses, never elapsed time. The observed point preview is provisional, not a finished textured model. A physical-device test is needed to assess tracking and food fidelity.

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

Hosted macOS CI checks the unsigned Xcode archive and spatial coverage logic. The video suite encodes and decodes actual MOV files, checking orientation, bounded photo selection, stationary/dark/short rejection, preservation of the source and protection against overwriting saved images. Database tests exercise offline admission/deduplication, tenant isolation, cancelled/stale leases, and private artifact delivery. These checks do not establish physical camera tracking, speed, surface quality, metric scale or food fidelity. A real iPhone scan and reconstruction remain required acceptance checks. No production scan was available during initial integration.

Apple references: [ARFrame raw feature points](https://developer.apple.com/documentation/arkit/arframe/rawfeaturepoints), [scene depth](https://developer.apple.com/documentation/arkit/arframe/scenedepth), [foreground instance masks](https://developer.apple.com/documentation/vision/vngenerateforegroundinstancemaskrequest). These APIs do not promise that raw feature points describe a complete object surface.

### Installed toolchain verification (2026-09-20)

The [hosted toolchain build](https://github.com/Omazi/dishplay3d/actions/runs/35531822310) succeeded. Its 748 MiB image archive was downloaded, SHA-256 checked and installed on the owner's Ubuntu PC. The reference dataset is [openMVG/ImageDataset_SceauxCastle](https://github.com/openMVG/ImageDataset_SceauxCastle/tree/fde7f5faba555e3c54700477c304488613346a19), pinned to `fde7f5faba555e3c54700477c304488613346a19`, with all 11 photos, 1600 px input, one CPU and a 1536 MiB container cap.

Actual execution exposed and fixed two OpenMVS interface/export issues: mesh stages produce separate PLY geometry while retaining camera poses in `dense.mvs`; the pinned OBJ exporter crashes for a single atlas, so the pipeline uses OpenMVS's native GLB export. Blender converts the imported unlit atlas material to a matte Principled surface so USD Preview Surface retains its actual image texture. Geometry and UVs remain from the reconstruction.

After resuming from the computed intermediates, every stage executed successfully and both final files passed structural checks and Blender reimport checks: GLB 10,310,168 bytes and USDZ 8,774,527 bytes. The export report records 43,404 faces and a readable texture in both formats. Local evidence is private under `.data/worker-validation/run-01/` (the original failure logs and continuation reports are retained). This is a building reference test; it does not establish food fidelity, metric scale, or iPhone Quick Look behavior.

The [web validation and deployment](https://github.com/Omazi/dishplay3d/actions/runs/35532964910) passed all 23 browser checks, including FR/EN, three original photo effects, three real illustrative GLBs, mobile layout and native transfer. [TestFlight 0.2.0 (3.1)](testflight.md) is available to the existing internal group.
