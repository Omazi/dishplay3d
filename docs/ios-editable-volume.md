# Adjustable capture volume (0.6)

## Flow

1. Open **Film and scan my dish**. Tracking locates the surface; manual centering remains available if detection fails.
2. Adjust the world-anchored box before recording: drag its six face handles, pinch to scale, drag/tap to move along its base plane, or rotate with two fingers. Width, height and depth also have an accessible slider. The bottom handle changes the base while keeping the top fixed. Sizes are estimated, bounded to 4–80 cm.
3. **Start recording** locks the selection. All corners must fit in the camera view and AR tracking must be normal. Setup never starts a movie or accepts reconstruction photos.
4. Follow the orange orbit. Video, accepted photographs and the lower provisional preview update together. The UI reports saved useful views and labels coverage as camera angles, not model quality. Sparse previews produce a warning.
5. Review, send, and follow the existing upload/PC-reconstruction receipt. The final USDZ supports Quick Look 3D/AR after the PC finishes. Final fidelity and scale still need review.

The capability-based preview supports phones without scene depth (observed feature points and a silhouette estimate) and uses actual scene-depth/mesh data when available. It does not depend on ObjectCaptureSession support. It is not Gaussian splatting or a finished mesh reconstructed in real time.

## Selection and source preservation

Observed points, measured triangles and the silhouette grid are limited to the selected box. Each accepted photograph is accompanied by the original under `Originals/`, camera pose/intrinsics and the selected volume under `Checkpoints/`. Upload uses a same-size JPEG derivative with a neutral background **outside the projected box**. This is not full object segmentation: background or occluders inside that projection can remain. Original video segments are preserved. Restart archives originals, derivatives and checkpoints together under `Retakes/` and leaves source movies intact.

The selection does not repair transparent lids, reflections, missing viewpoints or camera calibration. It does not establish millimetric size. The local worker continues to process at most 24 photos under its existing 1.5 GiB / one-CPU cap; no local training, new cloud service or paid AI integration is added.

Analysis and preview collection are throttled to one pass per 350 ms, including already-covered angles. Segmentation has one serial work item. Existing point, mesh, voxel and movie-buffer caps remain in effect.

## Reference review

The supplied [burger demonstration](https://www.tiktok.com/@arcodecom/video/7345780022835203334), [cake demonstration](https://ar-code.com/images/AR-Code-capture-cake.mp4), [YouTube demonstration](https://www.youtube.com/watch?v=xYjeymr1tDk), and [product page](https://ar-code.com/solutions/object-capture) show adjustable bounds, live observations and a separate final-model processing step. The supplied [AR GenAI restaurant video](https://ar-code.com/images/ar-genai-demo-restaurant.mp4) and [GenAI product](https://ar-code.com/solutions/ar-genai) demonstrate a different single-photo generative workflow. They are references, not evidence that DishPlay has their proprietary reconstruction engine or equivalent quality.

## Verification

Hosted Mac tests exercise rotated box containment, resize bounds, camera projection and background exclusion; a real Core Image/JPEG test checks asymmetric mask orientation, unchanged source image, output dimensions and invalid-selection rejection. Existing actual-MOV, silhouette, coverage, receipt and signing suites remain required. A full iOS archive must succeed before TestFlight distribution.

Physical acceptance remains necessary: drag every face handle on a real iPhone, rotate/reposition the box, confirm setup records nothing, scan an opaque textured dish, inspect the lower preview and preserved originals, interrupt/resume, upload, then inspect the resulting GLB/USDZ and AR placement. Automated tests cannot verify physical tracking, smoothness or final food fidelity.
